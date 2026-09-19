from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Department, Model, ProductionOrder, QualityCheck, Role, User, WorkOrder


def _headers(user: User, factory: str | None = None) -> dict[str, str]:
    selected = factory or user.factory_code
    token = create_access_token(user.id, extra={"factory_code": selected})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def quality_scope_data():
    db = SessionLocal()
    marker = uuid4().hex[:10]
    role = Role(name=f"Quality scope {marker}", permissions=["planning.production"])
    denied_role = Role(name=f"Quality denied {marker}", permissions=[])
    db.add_all([role, denied_role])
    db.flush()

    users = {}
    work_orders = {}
    department_codes = {"MIL": "CUT", "BST": "BST", "ECO": "ECP"}
    model = db.query(Model).first()
    assert model is not None
    for factory, department_code in department_codes.items():
        department = db.query(Department).filter(Department.code == department_code).one()
        order = ProductionOrder(
            production_no=f"QUALITY-SCOPE-{factory}-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=10,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="cutting" if factory == "MIL" else "sewing",
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        db.add(work_order)
        user = User(
            name=f"Quality {factory} {marker}",
            email=f"quality-{factory.lower()}-{marker}@example.invalid",
            password_hash="unused",
            role=role,
            factory_code=factory,
            extra_permissions=["factory:BST:planning.production"] if factory == "MIL" else [],
            is_active=True,
        )
        db.add(user)
        users[factory] = user
        work_orders[factory] = work_order
    denied = User(
        name=f"Quality denied {marker}",
        email=f"quality-denied-{marker}@example.invalid",
        password_hash="unused",
        role=denied_role,
        factory_code="MIL",
        is_active=True,
    )
    db.add(denied)
    db.commit()
    try:
        yield users, work_orders, denied
    finally:
        db.close()


def _payload(work_order_id: int) -> dict:
    return {"work_order_id": work_order_id, "checked_qty": 1, "passed_qty": 1, "failed_qty": 0}


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_quality_check_allows_same_factory_and_preserves_optional_department(
    client, quality_scope_data, factory,
):
    users, work_orders, _ = quality_scope_data
    response = client.post(
        "/api/quality/checks",
        json=_payload(work_orders[factory].id),
        headers=_headers(users[factory]),
    )
    assert response.status_code == 201, response.text
    assert response.json()["work_order_id"] == work_orders[factory].id
    assert response.json()["department_id"] is None


def test_quality_check_honors_explicit_selected_factory(client, quality_scope_data):
    users, work_orders, _ = quality_scope_data
    selected = client.post(
        "/api/quality/checks",
        json=_payload(work_orders["BST"].id),
        headers=_headers(users["MIL"], "BST"),
    )
    assert selected.status_code == 201, selected.text


@pytest.mark.parametrize(
    ("actor_factory", "target_factory"),
    [("MIL", "BST"), ("MIL", "ECO"), ("BST", "MIL"),
     ("BST", "ECO"), ("ECO", "MIL"), ("ECO", "BST")],
)
def test_quality_check_denies_all_other_factory_pairs(
    client, quality_scope_data, actor_factory, target_factory,
):
    users, work_orders, _ = quality_scope_data
    db = SessionLocal()
    before_denied = db.query(QualityCheck).count()
    before_audit = db.query(AuditLog).count()
    db.close()
    response = client.post(
        "/api/quality/checks",
        json=_payload(work_orders[target_factory].id),
        headers=_headers(users[actor_factory], actor_factory),
    )
    assert response.status_code == 403, response.text
    db = SessionLocal()
    assert db.query(QualityCheck).count() == before_denied
    assert db.query(AuditLog).count() == before_audit
    db.close()


def test_quality_check_role_without_floor_permission_is_denied(client, quality_scope_data):
    _, work_orders, denied = quality_scope_data
    response = client.post(
        "/api/quality/checks",
        json=_payload(work_orders["MIL"].id),
        headers=_headers(denied),
    )
    assert response.status_code == 403, response.text


def test_quality_check_missing_work_order_is_404(client, quality_scope_data):
    users, _, _ = quality_scope_data
    response = client.post(
        "/api/quality/checks",
        json=_payload(999_999_999),
        headers=_headers(users["MIL"]),
    )
    assert response.status_code == 404, response.text
