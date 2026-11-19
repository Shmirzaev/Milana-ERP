"""Customer create keeps mapped persistence inside the Catalog schema layer."""

import pytest
from sqlalchemy.orm import object_session

from app.libs.dto.catalog.party_input import PartyIn
from app.models.catalog import partners_service
from app.schemas import AuditLog, Customer
from app.schemas.catalog.partners_persistence import insert_customer
from app.tests.conftest import TestSessionLocal


def test_customer_create_returns_saved_fields_and_audits(client, auth_headers):
    response = client.post(
        "/api/customers",
        headers=auth_headers,
        json={
            "name": "Catalog Customer Create",
            "phone": "+998 90 123 45 67",
            "email": "catalog-customer@example.test",
            "address": "Factory road",
            "notes": "Created through the partner route",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert {key: body[key] for key in ("name", "phone", "email", "address", "notes")} == {
        "name": "Catalog Customer Create",
        "phone": "+998 90 123 45 67",
        "email": "catalog-customer@example.test",
        "address": "Factory road",
        "notes": "Created through the partner route",
    }
    with TestSessionLocal() as db:
        saved = db.get(Customer, body["id"])
        assert saved is not None
        assert saved.name == body["name"]
        assert db.query(AuditLog).filter_by(
            entity_type="Customer", entity_id=saved.id, action="create"
        ).count() == 1


def test_customer_create_requires_the_existing_route_permission(client):
    response = client.post("/api/customers", json={"name": "Denied Customer Create"})

    assert response.status_code == 401
    with TestSessionLocal() as db:
        assert db.query(Customer).filter_by(name="Denied Customer Create").count() == 0


def test_customer_persistence_flushes_on_supplied_session_without_committing():
    with TestSessionLocal() as db:
        customer = insert_customer(
            db,
            name="Uncommitted Customer",
            phone=None,
            email=None,
            address=None,
            notes=None,
        )
        assert customer.id is not None
        assert object_session(customer) is db
        assert db.in_transaction()
        assert db.query(Customer).filter_by(id=customer.id).one().name == "Uncommitted Customer"
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Customer).filter_by(name="Uncommitted Customer").count() == 0


def test_customer_audit_failure_rolls_back_insert_and_audit(monkeypatch):
    original_audit = partners_service.log_action
    attempted_ids = []

    def fail_after_audit(db, actor, action, entity_type, entity_id):
        customer = db.get(Customer, entity_id)
        assert customer is not None and object_session(customer) is db
        original_audit(db, actor, action, entity_type, entity_id)
        attempted_ids.append(entity_id)
        raise RuntimeError("injected customer audit failure")

    monkeypatch.setattr(partners_service, "log_action", fail_after_audit)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected customer audit failure"):
            partners_service.create_customer(
                None,
                db,
                PartyIn(name="Customer Retry After Rollback"),
            )
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Customer).filter_by(name="Customer Retry After Rollback").count() == 0
        assert db.query(AuditLog).filter_by(
            entity_type="Customer", entity_id=attempted_ids[0], action="create"
        ).count() == 0

    monkeypatch.setattr(partners_service, "log_action", original_audit)
    with TestSessionLocal() as db:
        created = partners_service.create_customer(
            None,
            db,
            PartyIn(name="Customer Retry After Rollback"),
        )
        assert created.id is not None
        assert created.phone is None and created.email is None
        assert db.query(AuditLog).filter_by(
            entity_type="Customer", entity_id=created.id, action="create"
        ).count() == 1
