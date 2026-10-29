"""Supplier create keeps mapped persistence inside the Catalog schema layer."""

import pytest
from sqlalchemy.orm import object_session

from app.libs.dto.catalog.party_input import PartyIn
from app.models.catalog import partners_service
from app.schemas import AuditLog, Supplier
from app.schemas.catalog.partners_persistence import insert_supplier
from app.tests.conftest import TestSessionLocal


def test_supplier_create_returns_saved_fields_and_audits(client, auth_headers):
    response = client.post(
        "/api/suppliers",
        headers=auth_headers,
        json={
            "name": "Catalog Supplier Create",
            "phone": "+998 90 123 45 67",
            "email": "catalog-supplier@example.test",
            "address": "Factory road",
            "notes": "Created through the partner route",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert {key: body[key] for key in ("name", "phone", "email", "address", "notes")} == {
        "name": "Catalog Supplier Create",
        "phone": "+998 90 123 45 67",
        "email": "catalog-supplier@example.test",
        "address": "Factory road",
        "notes": "Created through the partner route",
    }
    with TestSessionLocal() as db:
        saved = db.get(Supplier, body["id"])
        assert saved is not None
        assert saved.name == body["name"]
        assert db.query(AuditLog).filter_by(
            entity_type="Supplier", entity_id=saved.id, action="create"
        ).count() == 1


def test_supplier_create_requires_the_existing_route_permission(client):
    response = client.post("/api/suppliers", json={"name": "Denied Supplier Create"})

    assert response.status_code == 401
    with TestSessionLocal() as db:
        assert db.query(Supplier).filter_by(name="Denied Supplier Create").count() == 0


def test_supplier_persistence_flushes_on_supplied_session_without_committing():
    with TestSessionLocal() as db:
        supplier = insert_supplier(
            db,
            name="Uncommitted Supplier",
            phone=None,
            email=None,
            address=None,
            notes=None,
        )
        assert supplier.id is not None
        assert object_session(supplier) is db
        assert db.in_transaction()
        assert db.query(Supplier).filter_by(id=supplier.id).one().name == "Uncommitted Supplier"
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Supplier).filter_by(name="Uncommitted Supplier").count() == 0


def test_supplier_audit_failure_rolls_back_insert_and_audit(monkeypatch):
    original_audit = partners_service.log_action
    attempted_ids = []

    def fail_after_audit(db, actor, action, entity_type, entity_id):
        supplier = db.get(Supplier, entity_id)
        assert supplier is not None and object_session(supplier) is db
        original_audit(db, actor, action, entity_type, entity_id)
        attempted_ids.append(entity_id)
        raise RuntimeError("injected supplier audit failure")

    monkeypatch.setattr(partners_service, "log_action", fail_after_audit)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected supplier audit failure"):
            partners_service.create_supplier(
                None,
                db,
                PartyIn(name="Supplier Retry After Rollback"),
            )
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Supplier).filter_by(name="Supplier Retry After Rollback").count() == 0
        assert db.query(AuditLog).filter_by(
            entity_type="Supplier", entity_id=attempted_ids[0], action="create"
        ).count() == 0

    monkeypatch.setattr(partners_service, "log_action", original_audit)
    with TestSessionLocal() as db:
        created = partners_service.create_supplier(
            None,
            db,
            PartyIn(name="Supplier Retry After Rollback"),
        )
        assert created.id is not None
        assert created.phone is None and created.email is None
        assert db.query(AuditLog).filter_by(
            entity_type="Supplier", entity_id=created.id, action="create"
        ).count() == 1
