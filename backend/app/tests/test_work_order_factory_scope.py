from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Department, Model, ProductionOrder, Role, User, WorkOrder


def _headers(user: User, factory: str | None = None) -> dict[str, str]:
    selected = factory or user.factory_code
    token = create_access_token(user.id, extra={"factory_code": selected})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def work_order_scope_data():
    db = SessionLocal()
    marker = uuid4().hex[:10]
    role = Role(name=f"Work order scope {marker}", permissions=["planning.production"])
    denied_role = Role(name=f"Work order denied {marker}", permissions=[])
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
            production_no=f"WO-SCOPE-{factory}-{marker}",
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
            operation="printing",
            status="waiting",
            planned_input_qty=10,
            planned_output_qty=10,
        )
        db.add(work_order)
        user = User(
            name=f"Work order {factory} {marker}",
            email=f"work-order-{factory.lower()}-{marker}@example.invalid",
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
        name=f"Work order denied {marker}",
        email=f"work-order-denied-{marker}@example.invalid",
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


ACTIONS = {
    "start": ("post", "/start", None),
    "complete": ("post", "/complete", None),
    "update": ("patch", "", {"notes": "Scoped update"}),
    "reassign": ("patch", "", "assignee"),
    "pause": ("patch", "", {"status": "paused"}),
    "resume": ("patch", "", {"status": "ready"}),
    "collect": ("post", "/collect", {"deadline": "2026-12-01T00:00:00Z"}),
    "shortage": ("post", "/complete-cutting-shortage", None),
    "split": ("post", "/split-batches", {"batches": [{"planned_quantity": 10}]}),
    "extra": ("post", "/extra-batch", {"planned_quantity": 1}),
}


def _request(client, action, work_order_id, headers, assignee):
    method, suffix, payload = ACTIONS[action]
    if payload == "assignee":
        payload = {"assigned_to": assignee}
    kwargs = {"headers": headers}
    if payload is not None:
        kwargs["json"] = payload
    return getattr(client, method)(f"/api/work-orders/{work_order_id}{suffix}", **kwargs)


@pytest.mark.parametrize("action", list(ACTIONS))
@pytest.mark.parametrize("actor_factory,target_factory", [
    ("MIL", "BST"), ("MIL", "ECO"), ("BST", "MIL"),
    ("BST", "ECO"), ("ECO", "MIL"), ("ECO", "BST"),
])
def test_work_order_mutation_denies_other_factories(client, work_order_scope_data, action, actor_factory, target_factory):
    users, work_orders, _ = work_order_scope_data
    target = work_orders[target_factory]
    with SessionLocal() as db:
        before_audit = db.query(AuditLog).count()
        before = {key: getattr(db.get(WorkOrder, target.id), key) for key in
                  ("status", "notes", "assigned_to", "deadline", "start_time", "end_time")}
    response = _request(client, action, target.id, _headers(users[actor_factory], actor_factory), users[actor_factory].id)
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assert db.query(AuditLog).count() == before_audit
        assert {key: getattr(db.get(WorkOrder, target.id), key) for key in before} == before


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
@pytest.mark.parametrize("action", ["start", "complete", "update", "reassign", "pause", "resume", "collect"])
def test_work_order_mutation_allows_same_factory(client, work_order_scope_data, factory, action):
    users, work_orders, _ = work_order_scope_data
    response = _request(client, action, work_orders[factory].id, _headers(users[factory]), users[factory].id)
    # DB02-WO-STATUS requires explicit actions for transitions, even in the same factory.
    assert response.status_code == (409 if action in {"pause", "resume"} else 200), response.text


@pytest.mark.parametrize("action", ["start", "complete", "update"])
def test_work_order_mutation_honors_selected_factory(client, work_order_scope_data, action):
    users, work_orders, _ = work_order_scope_data
    response = _request(client, action, work_orders["BST"].id, _headers(users["MIL"], "BST"), users["BST"].id)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("action", ["start", "complete", "update", "collect", "shortage", "split", "extra"])
def test_work_order_mutation_missing_work_order_is_404(client, work_order_scope_data, action):
    users, _, _ = work_order_scope_data
    response = _request(client, action, 999_999_999, _headers(users["MIL"]), users["MIL"].id)
    assert response.status_code == 404, response.text
