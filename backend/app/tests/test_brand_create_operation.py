"""Brand-create behavior and transaction boundaries on isolated test data."""

import pytest
from sqlalchemy.orm import object_session

from app.libs.dto.catalog.brand_input import BrandIn
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand
from app.tests.conftest import TestSessionLocal


def test_brand_create_and_refusals(client, auth_headers):
    created = client.post(
        "/api/brands", headers=auth_headers,
        json={"name": "  Boundary Brand  ", "description": "catalog", "logo_url": "logo", "is_active": False},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert {k: body[k] for k in ("name", "description", "logo_url", "is_active")} == {
        "name": "Boundary Brand", "description": "catalog", "logo_url": "logo", "is_active": False,
    }
    duplicate = client.post("/api/brands", headers=auth_headers, json={"name": "boundary brand"})
    blank = client.post("/api/brands", headers=auth_headers, json={"name": "  "})
    assert (duplicate.status_code, duplicate.json()["detail"]) == (409, "Brand already exists")
    assert (blank.status_code, blank.json()["detail"]) == (400, "Brand name is required")
    with TestSessionLocal() as db:
        assert db.query(Brand).filter_by(name="Boundary Brand").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=body["id"], action="create").count() == 1


def test_audit_failure_rolls_back_insert_and_retry_succeeds(monkeypatch):
    original_audit = collections_service.log_action
    observed = []

    def fail_after_audit(db, actor, action, entity_type, entity_id):
        brand = db.get(Brand, entity_id)
        assert brand is not None and object_session(brand) is db
        original_audit(db, actor, action, entity_type, entity_id)
        observed.append(entity_id)
        raise RuntimeError("injected audit participant failure")

    monkeypatch.setattr(collections_service, "log_action", fail_after_audit)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit"):
            collections_service.create_brand(None, db, BrandIn(name="Retry Brand"))
        db.rollback()
    with TestSessionLocal() as db:
        assert db.query(Brand).filter_by(name="Retry Brand").count() == 0
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=observed[0]).count() == 0
    monkeypatch.setattr(collections_service, "log_action", original_audit)
    with TestSessionLocal() as db:
        brand = collections_service.create_brand(None, db, BrandIn(name="Retry Brand"))
        assert brand.is_active is True and brand.description is None and brand.logo_url is None
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=brand.id, action="create").count() == 1


def test_brand_create_requires_permission(client):
    response = client.post("/api/brands", json={"name": "Denied Brand"})
    assert response.status_code == 401
    with TestSessionLocal() as db:
        assert db.query(Brand).filter_by(name="Denied Brand").count() == 0
