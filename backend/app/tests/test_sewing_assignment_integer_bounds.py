from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.production import _sync_sewing_assignments_to_bundle_total
from app.db.session import SessionLocal
from app.models import AuditLog, Department, ProductionOrder, SewingAssignment, SewingFlow, WorkOrder


DB_INTEGER_MAX = 2_147_483_647
DB_INTEGER_MIN = -2_147_483_648


def _assignment_context(*, with_assignment: bool, completed_qty: int = 0) -> tuple[int, int, int | None]:
    marker = uuid4().hex[:12]
    with SessionLocal.begin() as db:
        department_id = db.query(Department.id).filter(Department.code == "SEW").scalar()
        order = ProductionOrder(
            production_no=f"ASSIGNMENT-BOUND-{marker}",
            production_type="branded_stock",
            model_id=1,
            planned_quantity=100,
        )
        flow = SewingFlow(
            factory_code="MIL",
            name=f"Assignment bound {marker}",
            code=f"AB-{marker}",
            is_active=True,
        )
        db.add_all([order, flow])
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department_id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=100,
            planned_output_qty=100,
        )
        db.add(work_order)
        db.flush()
        assignment_id = None
        if with_assignment:
            assignment = SewingAssignment(
                work_order_id=work_order.id,
                sewing_flow_id=flow.id,
                quantity=100,
                completed_qty=completed_qty,
                status="planned",
                notes="unchanged",
            )
            db.add(assignment)
            db.flush()
            assignment_id = assignment.id
        return work_order.id, flow.id, assignment_id


def _assignment_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.query(SewingAssignment).count(),
            db.query(AuditLog).filter(AuditLog.entity_type == "SewingAssignment").count(),
        )


def _assignment_state(assignment_id: int) -> tuple:
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        return (
            assignment.quantity,
            assignment.completed_qty,
            assignment.status,
            assignment.notes,
            db.query(AuditLog).filter(AuditLog.entity_type == "SewingAssignment").count(),
        )


def test_sewing_assignment_create_accepts_exact_integer_boundary(client, auth_headers):
    work_order_id, flow_id, _ = _assignment_context(with_assignment=False)

    response = client.post(
        f"/api/work-orders/{work_order_id}/assignments",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "sewing_flow_id": flow_id,
            "quantity": DB_INTEGER_MAX,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["quantity"] == DB_INTEGER_MAX
    with SessionLocal() as db:
        assert db.get(SewingAssignment, response.json()["id"]).quantity == DB_INTEGER_MAX


def test_sewing_assignment_create_rejects_integer_overflow_without_writes(
    client, auth_headers,
):
    work_order_id, flow_id, _ = _assignment_context(with_assignment=False)
    before = _assignment_counts()

    response = client.post(
        f"/api/work-orders/{work_order_id}/assignments",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "sewing_flow_id": flow_id,
            "quantity": DB_INTEGER_MAX + 1,
        },
    )

    assert response.status_code == 422, response.text
    assert _assignment_counts() == before
    with SessionLocal() as db:
        assert db.get(WorkOrder, work_order_id).sewing_flow_id is None


def test_sewing_assignment_patch_accepts_exact_integer_boundaries(client, auth_headers):
    _, _, assignment_id = _assignment_context(with_assignment=True)

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={"quantity": DB_INTEGER_MAX, "completed_qty": DB_INTEGER_MAX},
    )

    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == DB_INTEGER_MAX
    assert response.json()["completed_qty"] == DB_INTEGER_MAX


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": DB_INTEGER_MAX + 1},
        {"completed_qty": DB_INTEGER_MAX + 1},
        {"completed_qty": DB_INTEGER_MIN - 1},
    ],
)
def test_sewing_assignment_patch_rejects_integer_overflow_without_mutation(
    client, auth_headers, changes,
):
    _, _, assignment_id = _assignment_context(with_assignment=True)
    before = _assignment_counts()

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={**changes, "notes": "changed"},
    )

    assert response.status_code == 422, response.text
    assert _assignment_counts() == before
    with SessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        assert assignment.quantity == 100
        assert assignment.completed_qty == 0
        assert assignment.notes == "unchanged"


@pytest.mark.parametrize("changes", [
    {"completed_qty": -1},
    {"completed_qty": 101},
])
def test_sewing_assignment_patch_rejects_progress_outside_quantity_without_writes(
    client, auth_headers, changes,
):
    _, _, assignment_id = _assignment_context(with_assignment=True)
    before = _assignment_state(assignment_id)

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={**changes, "notes": "must not be saved"},
    )

    assert response.status_code == 409, response.text
    assert "progress" in response.text.lower()
    assert _assignment_state(assignment_id) == before


def test_sewing_assignment_cannot_be_resized_below_completed_progress(client, auth_headers):
    _, _, assignment_id = _assignment_context(with_assignment=True, completed_qty=60)
    before = _assignment_state(assignment_id)

    response = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        headers=auth_headers,
        json={"quantity": 50, "notes": "must not be saved"},
    )

    assert response.status_code == 409, response.text
    assert "progress" in response.text.lower()
    assert _assignment_state(assignment_id) == before


@pytest.mark.parametrize("target_quantity", [0, 1])
def test_cutting_resize_preserves_minimum_positive_quantity_per_assignment_without_writes(
    target_quantity,
):
    work_order_id, flow_id, _ = _assignment_context(with_assignment=True)
    with SessionLocal.begin() as db:
        db.add(SewingAssignment(
            work_order_id=work_order_id,
            sewing_flow_id=flow_id,
            quantity=1,
            completed_qty=0,
            status="planned",
        ))

    with SessionLocal() as db:
        work_order = db.get(WorkOrder, work_order_id)
        assignments = db.query(SewingAssignment).filter_by(work_order_id=work_order_id).order_by(
            SewingAssignment.id,
        ).all()
        before = [(row.quantity, row.completed_qty, row.status) for row in assignments]
        audit_count = db.query(AuditLog).filter(AuditLog.entity_type == "SewingAssignment").count()

        with pytest.raises(HTTPException) as error:
            _sync_sewing_assignments_to_bundle_total(db, work_order, None, target_quantity)

        assert error.value.status_code == 409
        assert "minimum active" in error.value.detail
        after = db.query(SewingAssignment).filter_by(work_order_id=work_order_id).order_by(
            SewingAssignment.id,
        ).all()
        assert [(row.quantity, row.completed_qty, row.status) for row in after] == before
        assert db.query(AuditLog).filter(AuditLog.entity_type == "SewingAssignment").count() == audit_count


def test_sewing_assignment_integer_bounds_preserve_auth_and_resource_precedence(
    client, auth_headers,
):
    work_order_id, _, assignment_id = _assignment_context(with_assignment=True)

    denied = client.patch(
        f"/api/sewing-assignments/{assignment_id}",
        json={"quantity": DB_INTEGER_MAX + 1},
    )
    assert denied.status_code == 401, denied.text

    missing_assignment = client.patch(
        "/api/sewing-assignments/2147483647",
        headers=auth_headers,
        json={"quantity": DB_INTEGER_MAX + 1},
    )
    assert missing_assignment.status_code == 404, missing_assignment.text

    missing_flow = client.post(
        f"/api/work-orders/{work_order_id}/assignments",
        headers=auth_headers,
        json={
            "work_order_id": work_order_id,
            "sewing_flow_id": 2_147_483_647,
            "quantity": DB_INTEGER_MAX + 1,
        },
    )
    assert missing_flow.status_code == 404, missing_flow.text
