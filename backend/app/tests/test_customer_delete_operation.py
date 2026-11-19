"""Customer delete keeps its authorization, guards and transaction boundary."""
from uuid import uuid4

import pytest
from sqlalchemy.orm import object_session

from app.core.security import create_access_token
from app.models.catalog import partners_service
from app.schemas import AuditLog, Customer, Role, SalesOrder, Shipment, User
from app.tests.conftest import TestSessionLocal


def actor(permissions):
    marker = uuid4().hex
    with TestSessionLocal() as db:
        role = Role(name=f"Delete role {marker}", permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name="Delete actor", email=f"delete-{marker}@example.invalid",
                    password_hash="unused", role_id=role.id, factory_code="MIL", is_active=True)
        db.add(user)
        db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(user.id)}"}


def seed_customer(*, sales=False, shipment=False):
    marker = uuid4().hex
    with TestSessionLocal() as db:
        row = Customer(name=f"Delete {marker}")
        db.add(row)
        db.flush()
        if sales:
            db.add(SalesOrder(order_no=f"SO-{marker}", customer_id=row.id))
        if shipment:
            db.add(Shipment(shipment_no=f"SH-{marker}", customer_id=row.id))
        db.commit()
        return row.id, row.name


def test_real_roles_delete_and_missing_with_same_session_audit(client, monkeypatch):
    cid, name = seed_customer()
    actor_id, allowed = actor(["sales.customers"])
    _, denied = actor(["sales.view"])
    original = partners_service.delete_customer_row
    seen = []
    def spy(db, row):
        assert object_session(row) is db
        seen.append((db, row.id, row.name))
        original(db, row)
    monkeypatch.setattr(partners_service, "delete_customer_row", spy)
    assert client.delete(f"/api/customers/{cid}").status_code == 401
    assert client.delete(f"/api/customers/{cid}", headers=denied).status_code == 403
    with TestSessionLocal() as db:
        assert db.get(Customer, cid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").count() == 0
    assert client.delete(f"/api/customers/{cid}", headers=allowed).status_code == 204
    assert len(seen) == 1 and seen[0][1:] == (cid, name)
    assert client.delete(f"/api/customers/{cid}", headers=allowed).status_code == 404
    with TestSessionLocal() as db:
        assert db.get(Customer, cid) is None
        audit = db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").one()
        assert audit.user_id == actor_id and audit.new_value_json == {"name": name}


@pytest.mark.parametrize("sales,shipment,message", [
    (True, False, "Customer is linked to sales orders"),
    (False, True, "Customer is linked to shipments"),
    (True, True, "Customer is linked to sales orders"),
])
def test_linked_refusals_leave_row_and_audit_unchanged(client, sales, shipment, message):
    cid, name = seed_customer(sales=sales, shipment=shipment)
    _, headers = actor(["sales.customers"])
    response = client.delete(f"/api/customers/{cid}", headers=headers)
    assert response.status_code == 409 and response.json() == {"detail": message}
    with TestSessionLocal() as db:
        assert db.get(Customer, cid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").count() == 0


def test_audit_failure_rolls_back_delete_then_explicit_retry(monkeypatch):
    cid, name = seed_customer()
    original = partners_service.log_action
    def fail(db, user, action, entity_type, entity_id, **kwargs):
        original(db, user, action, entity_type, entity_id, **kwargs)
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(partners_service, "log_action", fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            partners_service.delete_customer(None, db, cid)
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(Customer, cid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").count() == 0
    monkeypatch.setattr(partners_service, "log_action", original)
    with TestSessionLocal() as db:
        partners_service.delete_customer(None, db, cid)
    with TestSessionLocal() as db:
        assert db.get(Customer, cid) is None
        assert db.query(AuditLog).filter_by(entity_type="Customer", entity_id=cid, action="delete").one().new_value_json == {"name": name}
