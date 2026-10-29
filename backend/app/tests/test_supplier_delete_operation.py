"""Supplier delete preserves route permissions, guards and transaction ownership."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import object_session

from app.core.security import create_access_token
from app.models.catalog import partners_service
from app.schemas import AuditLog, PurchaseOrder, PurchaseRequestLine, Role, StockBatch, Supplier, User
from app.tests.conftest import TestSessionLocal


def actor(permissions):
    marker = uuid4().hex
    with TestSessionLocal() as db:
        role = Role(name=f"Supplier delete {marker}", permissions=permissions)
        db.add(role)
        db.flush()
        user = User(name="Supplier delete actor", email=f"supplier-delete-{marker}@example.invalid",
                    password_hash="unused", role_id=role.id, factory_code="MIL", is_active=True)
        db.add(user)
        db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(user.id)}"}


def seed_supplier():
    with TestSessionLocal() as db:
        row = Supplier(name=f"Delete supplier {uuid4().hex}")
        db.add(row)
        db.commit()
        return row.id, row.name


def test_route_role_refusals_delete_and_repeat(client, monkeypatch):
    sid, name = seed_supplier()
    actor_id, allowed = actor(["storage.suppliers"])
    _, denied = actor(["sales.view"])
    original = partners_service.delete_supplier_row
    observed = []

    def spy(db, row):
        assert object_session(row) is db
        observed.append((row.id, row.name))
        original(db, row)

    monkeypatch.setattr(partners_service, "delete_supplier_row", spy)
    assert client.delete(f"/api/suppliers/{sid}").status_code == 401
    assert client.delete(f"/api/suppliers/{sid}", headers=denied).status_code == 403
    with TestSessionLocal() as db:
        assert db.get(Supplier, sid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=sid, action="delete").count() == 0
    assert client.delete(f"/api/suppliers/{sid}", headers=allowed).status_code == 204
    assert observed == [(sid, name)]
    assert client.delete(f"/api/suppliers/{sid}", headers=allowed).status_code == 404
    with TestSessionLocal() as db:
        assert db.get(Supplier, sid) is None
        audit = db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=sid, action="delete").one()
        assert audit.user_id == actor_id and audit.new_value_json == {"name": name}


@pytest.mark.parametrize("hit", [0, 1, 2])
def test_guard_order_and_short_circuit_preserve_row(hit, monkeypatch):
    db = MagicMock()
    db.get.return_value = Supplier(id=17, name="Linked")
    calls = []
    expected = [StockBatch.id, PurchaseRequestLine.id, PurchaseOrder.id]

    def query(column):
        index = len(calls)
        calls.append(column)
        result = MagicMock()
        result.filter.return_value.first.return_value = (1,) if index == hit else None
        return result

    db.query.side_effect = query
    writer = MagicMock()
    monkeypatch.setattr(partners_service, "delete_supplier_row", writer)
    with pytest.raises(HTTPException) as refusal:
        partners_service.delete_supplier(None, db, 17)
    assert refusal.value.status_code == 409
    assert refusal.value.detail == "Supplier is linked to stock or purchasing records and cannot be deleted"
    assert len(calls) == hit + 1 and all(actual is wanted for actual, wanted in zip(calls, expected))
    writer.assert_not_called()
    db.commit.assert_not_called()


def test_audit_failure_rolls_back_then_retry(monkeypatch):
    sid, name = seed_supplier()
    original = partners_service.log_action

    def fail(db, user, action, entity_type, entity_id, **kwargs):
        original(db, user, action, entity_type, entity_id, **kwargs)
        raise RuntimeError("injected supplier audit failure")

    monkeypatch.setattr(partners_service, "log_action", fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected supplier audit failure"):
            partners_service.delete_supplier(None, db, sid)
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(Supplier, sid).name == name
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=sid, action="delete").count() == 0
    monkeypatch.setattr(partners_service, "log_action", original)
    with TestSessionLocal() as db:
        partners_service.delete_supplier(None, db, sid)
    with TestSessionLocal() as db:
        assert db.get(Supplier, sid) is None
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=sid, action="delete").one().new_value_json == {"name": name}
