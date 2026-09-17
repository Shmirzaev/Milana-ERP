"""Assignment deletion must honor the factory selected for the current session."""

from itertools import permutations
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Department, ProductionOrder, SewingAssignment, SewingFlow, User, WorkOrder


FACTORIES = ("MIL", "BST", "ECO")


def _actor(factory="MIL", permissions=("sewing.flows",)):
    with SessionLocal() as db:
        user = User(
            name="Assignment delete scope",
            email=f"assignment-delete-{uuid4().hex}@example.invalid",
            password_hash="unused-by-synthetic-token-test",
            factory_code=factory,
            extra_permissions=list(permissions),
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def _headers(user_id, factory):
    return {"Authorization": f"Bearer {create_access_token(user_id, {'factory_code': factory})}"}


def _assignment(factory="MIL", *, flow_active=True):
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        department_code = {"MIL": "SEW", "BST": "BST", "ECO": "ECO"}[factory]
        department = db.query(Department).filter_by(code=department_code).first()
        if department is None:
            department = Department(name=f"Delete scope {factory}", code=department_code)
            db.add(department)
            db.flush()
        production = ProductionOrder(
            production_no=f"PO-DELETE-{suffix}", production_type="branded_stock", model_id=1, planned_quantity=100
        )
        flow = SewingFlow(factory_code=factory, name=f"Delete {suffix}", code=f"DEL-{suffix}", is_active=flow_active)
        db.add_all([production, flow])
        db.flush()
        work_order = WorkOrder(
            production_order_id=production.id,
            department_id=department.id,
            operation="sewing",
            status="in_progress",
            planned_input_qty=100,
            planned_output_qty=100,
            sewing_flow_id=flow.id,
        )
        db.add(work_order)
        db.flush()
        assignment = SewingAssignment(
            work_order_id=work_order.id, sewing_flow_id=flow.id, quantity=100, completed_qty=0, status="planned"
        )
        db.add(assignment)
        db.commit()
        return [(SewingAssignment, assignment.id), (WorkOrder, work_order.id),
                (SewingFlow, flow.id), (ProductionOrder, production.id)]


def _snapshot(references):
    with SessionLocal() as db:
        rows = {}
        for model, row_id in references:
            row = db.get(model, row_id)
            rows[model.__tablename__] = (
                {column.name: getattr(row, column.name) for column in model.__table__.columns} if row else None
            )
        rows["audit_count"] = db.query(AuditLog).count()
        return rows


@pytest.mark.parametrize(("session_factory", "target_factory"), list(permutations(FACTORIES, 2)))
@pytest.mark.parametrize("permissions", [("sewing.flows",), ("*", "admin.super")])
def test_assignment_delete_rejects_other_factory_without_any_writes(
    client, session_factory, target_factory, permissions
):
    actor_id = _actor(session_factory, permissions)
    references = _assignment(target_factory)
    assignment_id = references[0][1]
    flow_id = references[2][1]
    before = _snapshot(references)
    writes = []
    with SessionLocal() as db:
        engine = db.get_bind()

    def capture_write(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        headers = _headers(actor_id, session_factory)
        protected = client.post(
            f"/api/sewing-assignments/{assignment_id}/return", json={"sewing_flow_id": flow_id}, headers=headers
        )
        response = client.delete(f"/api/sewing-assignments/{assignment_id}", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)

    assert protected.status_code == 403, protected.text
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == protected.json()["detail"]
    assert writes == [], "Factory authorization must precede database mutations"
    assert _snapshot(references) == before


@pytest.mark.parametrize("factory", FACTORIES)
@pytest.mark.parametrize("permissions", [("sewing.flows",), ("planning.production",), ("*", "admin.super")])
def test_assignment_delete_allows_existing_permissions_in_selected_factory(client, factory, permissions):
    actor_id = _actor(factory, permissions)
    references = _assignment(factory)
    assignment_id = references[0][1]
    before = _snapshot(references)

    response = client.delete(f"/api/sewing-assignments/{assignment_id}", headers=_headers(actor_id, factory))

    assert response.status_code == 204, response.text
    after = _snapshot(references)
    assert after["sewing_assignments"] is None
    assert after["audit_count"] == before["audit_count"] + 1
    for table in ("work_orders", "sewing_flows", "production_orders"):
        assert after[table] == before[table]
    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(action="delete", entity_type="SewingAssignment", entity_id=assignment_id).one()
        assert audit.user_id == actor_id


def test_secondary_factory_grant_requires_selected_factory(client):
    actor_id = _actor(permissions=("sewing.flows", "factory:BST:sewing.flows"))
    references = _assignment("BST")
    assignment_id = references[0][1]
    before = _snapshot(references)

    wrong_session = client.delete(f"/api/sewing-assignments/{assignment_id}", headers=_headers(actor_id, "MIL"))

    assert wrong_session.status_code == 403
    assert _snapshot(references) == before
    selected_session = client.delete(f"/api/sewing-assignments/{assignment_id}", headers=_headers(actor_id, "BST"))
    assert selected_session.status_code == 204, selected_session.text


@pytest.mark.parametrize("permissions", [(), ("sewing.records",)])
def test_assignment_delete_still_requires_existing_delete_permission(client, permissions):
    actor_id = _actor(permissions=permissions)
    references = _assignment()
    before = _snapshot(references)

    response = client.delete(f"/api/sewing-assignments/{references[0][1]}", headers=_headers(actor_id, "MIL"))

    assert response.status_code == 403
    assert _snapshot(references) == before


def test_assignment_delete_still_allows_inactive_own_factory_line(client):
    actor_id = _actor()
    references = _assignment(flow_active=False)
    response = client.delete(f"/api/sewing-assignments/{references[0][1]}", headers=_headers(actor_id, "MIL"))

    assert response.status_code == 204, response.text


def test_assignment_delete_missing_assignment_stays_404(client):
    actor_id = _actor()
    response = client.delete("/api/sewing-assignments/2000000000", headers=_headers(actor_id, "MIL"))

    assert response.status_code == 404
    assert response.json()["detail"] == "Assignment not found"


def test_assignment_delete_missing_flow_fails_closed(client):
    actor_id = _actor()
    references = _assignment()
    assignment_id = references[0][1]
    with SessionLocal() as db:
        db.get(SewingAssignment, assignment_id).sewing_flow_id = 2_000_000_000
        db.commit()
    before = _snapshot(references)

    response = client.delete(f"/api/sewing-assignments/{assignment_id}", headers=_headers(actor_id, "MIL"))

    assert response.status_code == 404
    assert response.json()["detail"] == "Sewing flow not found"
    assert _snapshot(references) == before
