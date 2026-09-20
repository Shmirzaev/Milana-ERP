"""Generic work-order commands honor stage and selected-factory scope."""

from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import AuditLog, Department, ProductionOrder, User, WorkOrder
from app.tests.conftest import TestSessionLocal


def _work_order(operation: str, department_code: str, *, source_type: str = "standard") -> int:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        order = ProductionOrder(
            production_no=f"WO-SCOPE-{marker}",
            production_type="service_order" if source_type == "usluga" else "branded_stock",
            source_type=source_type,
            model_id=1,
            status="planning",
            planned_quantity=10,
        )
        db.add(order)
        db.flush()
        department_id = db.query(Department.id).filter(Department.code == department_code).scalar()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation=operation,
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        db.add(work_order)
        db.commit()
        return work_order.id


def _headers(email: str, *, factory_code: str = "MIL") -> dict[str, str]:
    with TestSessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        token = create_access_token(user.id, extra={"factory_code": factory_code})
    return {"Authorization": f"Bearer {token}"}


def _scoped_user(*, factory_code: str, permissions: list[str]) -> int:
    with TestSessionLocal() as db:
        user = User(
            name="Work-order scope test",
            email=f"wo-scope-{uuid4().hex}@example.com",
            password_hash="test-only",
            factory_code=factory_code,
            extra_permissions=permissions,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _token_headers(user_id: int, factory_code: str) -> dict[str, str]:
    token = create_access_token(user_id, extra={"factory_code": factory_code})
    return {"Authorization": f"Bearer {token}"}


def _command(client, command: str, work_order_id: int, headers: dict[str, str]):
    if command == "update":
        return client.patch(
            f"/api/work-orders/{work_order_id}",
            json={"notes": "scoped update"},
            headers=headers,
        )
    return client.post(f"/api/work-orders/{work_order_id}/{command}", headers=headers)


def _state(work_order_id: int) -> tuple[str, str | None, int]:
    with TestSessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        audit_count = db.query(AuditLog).filter(
            AuditLog.entity_type == "WorkOrder",
            AuditLog.entity_id == work_order_id,
        ).count()
        return work_order.status, work_order.notes, audit_count


@pytest.mark.parametrize("command", ["update", "start", "complete"])
def test_wrong_stage_cannot_run_generic_work_order_commands(client, command):
    work_order_id = _work_order("printing", "PRT")
    before = _state(work_order_id)

    response = _command(client, command, work_order_id, _headers("cutting@example.com"))

    assert response.status_code == 403, response.text
    assert _state(work_order_id) == before


def test_work_order_commands_require_authentication(client):
    work_order_id = _work_order("cutting", "CUT")
    before = _state(work_order_id)

    response = client.patch(
        f"/api/work-orders/{work_order_id}",
        json={"notes": "anonymous update"},
    )

    assert response.status_code in (401, 403), response.text
    assert _state(work_order_id) == before


@pytest.mark.parametrize(
    ("operation", "department", "email"),
    [
        ("cutting", "CUT", "cutting@example.com"),
        ("printing", "PRT", "printing@example.com"),
        ("sewing", "MIL", "sewing@example.com"),
        ("packaging", "PKG", "packaging@example.com"),
        ("storage_transfer", "FGS", "storage@example.com"),
    ],
)
def test_own_stage_can_keep_using_generic_metadata_update(client, operation, department, email):
    work_order_id = _work_order(operation, department)

    response = _command(client, "update", work_order_id, _headers(email))

    assert response.status_code == 200, response.text
    assert response.json()["notes"] == "scoped update"


@pytest.mark.parametrize("command", ["start", "complete"])
def test_own_stage_can_keep_using_explicit_commands(client, command):
    work_order_id = _work_order("printing", "PRT")

    response = _command(client, command, work_order_id, _headers("printing@example.com"))

    assert response.status_code == 200, response.text


def test_generic_manual_status_and_counter_update_remains_supported(client):
    work_order_id = _work_order("printing", "PRT")

    response = client.patch(
        f"/api/work-orders/{work_order_id}",
        json={
            "status": "in_progress",
            "actual_input_qty": 3,
            "actual_output_qty": 2,
            "passed_qty": 2,
            "failed_qty": 1,
            "rework_qty": 0,
        },
        headers=_headers("printing@example.com"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "in_progress"
    assert response.json()["actual_input_qty"] == 3
    assert response.json()["passed_qty"] == 2


@pytest.mark.parametrize("email", ["planning@example.com", "admin@example.com"])
def test_planning_and_admin_keep_cross_stage_update_access(client, email):
    work_order_id = _work_order("packaging", "PKG")

    response = _command(client, "update", work_order_id, _headers(email))

    assert response.status_code == 200, response.text


def test_factory_grant_requires_selecting_target_factory(client):
    work_order_id = _work_order("sewing", "BST")
    user_id = _scoped_user(
        factory_code="MIL",
        permissions=["sewing.records", "factory:BST:sewing.records"],
    )
    before = _state(work_order_id)

    denied = _command(client, "update", work_order_id, _token_headers(user_id, "MIL"))
    assert denied.status_code == 403, denied.text
    assert _state(work_order_id) == before

    allowed = _command(client, "update", work_order_id, _token_headers(user_id, "BST"))

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["notes"] == "scoped update"


@pytest.mark.parametrize("command", ["update", "start", "complete"])
def test_usluga_commands_require_eco_factory_context(client, command):
    work_order_id = _work_order("cutting", "ECT", source_type="usluga")
    before = _state(work_order_id)

    denied = _command(client, command, work_order_id, _headers("cutting@example.com"))

    assert denied.status_code == 403, denied.text
    assert _state(work_order_id) == before


@pytest.mark.parametrize("command", ["update", "start", "complete"])
def test_legacy_usluga_department_cannot_bypass_eco_factory_scope(client, command):
    work_order_id = _work_order("cutting", "CUT", source_type="usluga")
    before = _state(work_order_id)

    denied = _command(client, command, work_order_id, _headers("cutting@example.com"))

    assert denied.status_code == 403, denied.text
    assert _state(work_order_id) == before


@pytest.mark.parametrize("command", ["update", "start", "complete"])
def test_eco_stage_user_can_run_usluga_commands(client, command):
    work_order_id = _work_order("cutting", "ECT", source_type="usluga")
    user_id = _scoped_user(factory_code="ECO", permissions=["cutting.records"])

    response = _command(client, command, work_order_id, _token_headers(user_id, "ECO"))

    assert response.status_code == 200, response.text


def test_unknown_work_order_operation_fails_closed(client, auth_headers):
    work_order_id = _work_order("quality", "MIL")
    before = _state(work_order_id)

    response = _command(client, "update", work_order_id, auth_headers)

    assert response.status_code == 403, response.text
    assert _state(work_order_id) == before
