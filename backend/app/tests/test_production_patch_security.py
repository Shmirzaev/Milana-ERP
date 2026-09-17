"""Generic planning edits must not bypass the production workflow."""
import pytest

from app.core.security import create_access_token
from app.models import Department, ProductionOrder, Role, User, WorkOrder
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def planning_order():
    with TestSessionLocal() as db:
        role = Role(name="Patch security planner", permissions=["planning.production"])
        db.add(role)
        db.flush()
        actor = User(name="Patch planner", email="patch-planner@example.com",
                     password_hash="unused", role_id=role.id, factory_code="MIL", is_active=True)
        db.add(actor)
        db.flush()
        po = ProductionOrder(production_no="PATCH-SECURITY", production_type="branded_stock",
                             model_id=1, planned_quantity=10, status="planning", created_by=actor.id)
        db.add(po)
        db.flush()
        department = db.query(Department).filter_by(code="CUT").one()
        db.add(WorkOrder(production_order_id=po.id, operation="cutting", department_id=department.id,
                         status="ready", planned_input_qty=10, planned_output_qty=10))
        db.commit()
        return po.id, actor.id, {"Authorization": f"Bearer {create_access_token(str(actor.id))}"}


@pytest.mark.parametrize("field,value", [
    ("status", "completed"), ("created_by", 1), ("id", 999),
    ("production_no", "FORGED"), ("source_type", "usluga"),
    ("created_at", "2020-01-01T00:00:00Z"), ("items", []),
    ("production_type", "client_order"), ("unexpected", True),
])
@pytest.mark.parametrize("administrator", [False, True])
def test_internal_fields_rejected_atomically(client, auth_headers, planning_order, field, value, administrator):
    pid, creator, planner_headers = planning_order
    response = client.patch(f"/api/production-orders/{pid}",
                            json={field: value, "planned_quantity": 25},
                            headers=auth_headers if administrator else planner_headers)
    assert response.status_code == 422, response.text
    with TestSessionLocal() as db:
        po = db.get(ProductionOrder, pid)
        assert (po.status, po.created_by, po.planned_quantity) == ("planning", creator, 10)
        assert po.production_no == "PATCH-SECURITY"


def test_planning_edits_keep_workflow_and_creator(client, planning_order):
    pid, creator, headers = planning_order
    response = client.patch(f"/api/production-orders/{pid}", headers=headers, json={
        "model_id": 1, "sales_order_id": None, "planned_quantity": 25,
        "deadline": "2026-10-01T00:00:00Z", "estimated_material_code": "FAB-1",
        "estimated_material_amount": 12.5, "estimated_material_unit": "kg",
        "printing_instructions": "Use approved artwork", "printing_attachments": [],
    })
    assert response.status_code == 200, response.text
    assert response.json()["planned_quantity"] == 25
    assert response.json()["deadline"].startswith("2026-10-01")
    with TestSessionLocal() as db:
        po = db.get(ProductionOrder, pid)
        assert (po.status, po.created_by) == ("planning", creator)
        assert float(po.estimated_material_amount) == 12.5
    assert client.patch(f"/api/production-orders/{pid}", headers=headers,
                        json={"deadline": None}).status_code == 200


@pytest.mark.parametrize("payload", [{"planned_quantity": None}, {"model_id": None},
                                   {"planned_quantity": -1}, {"estimated_material_amount": -1}])
def test_invalid_planning_fields_rejected(client, planning_order, payload):
    pid, _, headers = planning_order
    assert client.patch(f"/api/production-orders/{pid}", headers=headers, json=payload).status_code == 422


def test_planning_patch_preserves_cutting_lock_and_usluga_isolation(client, planning_order):
    pid, _, headers = planning_order
    with TestSessionLocal() as db:
        db.query(WorkOrder).filter_by(production_order_id=pid).one().status = "in_progress"
        db.commit()
    assert client.patch(f"/api/production-orders/{pid}", headers=headers,
                        json={"planned_quantity": 30}).status_code == 409
    with TestSessionLocal() as db:
        po = db.get(ProductionOrder, pid)
        assert po.planned_quantity == 10
        po.source_type = "usluga"
        db.commit()
    assert client.patch(f"/api/production-orders/{pid}", headers=headers,
                        json={"printing_instructions": "cross-workflow"}).status_code == 409


def test_patch_requires_planning_permission(client, planning_order):
    pid, creator, headers = planning_order
    with TestSessionLocal() as db:
        actor = db.get(User, creator)
        db.get(Role, actor.role_id).permissions = []
        db.commit()
    assert client.patch(f"/api/production-orders/{pid}", headers=headers,
                        json={"planned_quantity": 30}).status_code == 403
