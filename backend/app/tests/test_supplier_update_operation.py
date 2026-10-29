"""Supplier PATCH preserves its legacy field and transaction contract."""
import pytest
from sqlalchemy.orm import object_session

from app.libs.dto.catalog.party_input import PartyIn
from app.models.catalog import partners_service
from app.schemas import AuditLog, Supplier
from app.tests.conftest import TestSessionLocal


def seed_supplier():
    with TestSessionLocal() as db:
        row = Supplier(name="Original", phone="old phone", email="old email", address="old address", notes="old notes")
        db.add(row)
        db.commit()
        return row.id


def test_patch_omitted_null_empty_and_refusals(client, auth_headers):
    cid = seed_supplier()
    url = f"/api/suppliers/{cid}"
    result = client.patch(url, headers=auth_headers, json={"name": "  Updated  ", "phone": None, "notes": ""})
    assert result.status_code == 200, result.text
    assert {k: result.json()[k] for k in ("name", "phone", "email", "address", "notes")} == {
        "name": "  Updated  ", "phone": None, "email": "old email", "address": "old address", "notes": ""}
    assert client.patch(url, headers=auth_headers, json={"phone": "x"}).status_code == 422
    assert client.patch(url, headers=auth_headers, json={"name": None}).status_code == 422
    assert client.patch(url, headers=auth_headers, json={"name": "x" * 256}).status_code == 422
    assert client.patch(url, headers=auth_headers, json={"name": "ok", "phone": "x" * 65}).status_code == 422
    assert client.patch(url, headers=auth_headers, json={"name": "ok", "email": "x" * 256}).status_code == 422
    assert client.patch("/api/suppliers/2147483647", headers=auth_headers, json={"name": "missing"}).status_code == 404
    assert client.patch(url, json={"name": "denied"}).status_code == 401
    with TestSessionLocal() as db:
        assert db.get(Supplier, cid).name == "  Updated  "
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 1


def test_inactive_supplier_patch_by_id_does_not_activate_or_list(client, auth_headers):
    with TestSessionLocal() as db:
        row = Supplier(name="Inactive before", phone="old", is_active=False)
        db.add(row)
        db.commit()
        sid = row.id
    response = client.patch(f"/api/suppliers/{sid}", headers=auth_headers,
                            json={"name": "Inactive after", "phone": None, "is_active": True})
    assert response.status_code == 200, response.text
    assert response.json()["phone"] is None
    listing = client.get("/api/suppliers", headers=auth_headers)
    assert listing.status_code == 200
    assert sid not in {row["id"] for row in listing.json()}
    with TestSessionLocal() as db:
        saved = db.get(Supplier, sid)
        assert (saved.name, saved.phone, saved.is_active) == ("Inactive after", None, False)


def test_writer_receives_same_session_and_only_supplied_fields(monkeypatch):
    cid = seed_supplier()
    original = partners_service.apply_supplier_update
    seen = []
    def spy(db, supplier, fields):
        assert object_session(supplier) is db
        seen.append((db, supplier, dict(fields)))
        return original(db, supplier, fields)
    monkeypatch.setattr(partners_service, "apply_supplier_update", spy)
    with TestSessionLocal() as db:
        row = partners_service.update_supplier(None, db, cid, PartyIn(name="New", email=None))
        assert seen == [(db, row, {"name": "New", "email": None})]
        assert row.phone == "old phone" and row.email is None


def test_audit_failure_rolls_back_then_explicit_retry(monkeypatch):
    cid = seed_supplier()
    original = partners_service.log_action
    def fail(db, actor, action, entity_type, entity_id):
        assert object_session(db.get(Supplier, entity_id)) is db
        original(db, actor, action, entity_type, entity_id)
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(partners_service, "log_action", fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit failure"):
            partners_service.update_supplier(None, db, cid, PartyIn(name="Changed", notes=None))
        db.rollback()
    with TestSessionLocal() as db:
        assert (db.get(Supplier, cid).name, db.get(Supplier, cid).notes) == ("Original", "old notes")
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 0
    monkeypatch.setattr(partners_service, "log_action", original)
    with TestSessionLocal() as db:
        partners_service.update_supplier(None, db, cid, PartyIn(name="Changed", notes=None))
    with TestSessionLocal() as db:
        assert (db.get(Supplier, cid).name, db.get(Supplier, cid).notes) == ("Changed", None)
        assert db.query(AuditLog).filter_by(entity_type="Supplier", entity_id=cid, action="update").count() == 1
