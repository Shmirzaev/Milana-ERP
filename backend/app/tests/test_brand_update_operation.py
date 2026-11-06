"""Characterize the existing Brand PATCH contract and transaction boundary."""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session
from app.libs.dto.catalog.brand_input import BrandIn
from app.models.catalog import collections_service
from app.schemas import AuditLog, Brand
from app.tests.conftest import TestSessionLocal


def seed_brand(name="Original"):
    with TestSessionLocal() as db:
        row = Brand(name=name, description="old", logo_url="logo", is_active=False)
        db.add(row); db.commit(); return row.id


def test_patch_fields_refusals_and_audit(client, auth_headers):
    bid = seed_brand()
    url = f"/api/brands/{bid}"
    r = client.patch(url, headers=auth_headers, json={"name": "  Updated  "})
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("name", "description", "logo_url", "is_active")} == {
        "name": "  Updated  ", "description": "old", "logo_url": "logo", "is_active": False}
    r = client.patch(url, headers=auth_headers, json={"name": "", "description": None, "logo_url": None, "is_active": False})
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ("name", "description", "logo_url", "is_active")} == {
        "name": "", "description": None, "logo_url": None, "is_active": False}
    for payload in ({"description": "no name"}, {"name": None}, {"name": "ok", "is_active": None}):
        assert client.patch(url, headers=auth_headers, json=payload).status_code == 422
    assert client.patch('/api/brands/99999999', headers=auth_headers, json={"name": "missing"}).status_code == 404
    assert client.patch(url, json={"name": "denied"}).status_code == 401
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == ""
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 2


def test_audit_failure_rolls_back_and_explicit_retry(monkeypatch):
    bid = seed_brand()
    original = collections_service.log_action
    def fail(db, actor, action, entity_type, entity_id):
        assert object_session(db.get(Brand, entity_id)) is db
        original(db, actor, action, entity_type, entity_id)
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(collections_service, "log_action", fail)
    with TestSessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected audit"):
            collections_service.update_brand(None, db, bid, BrandIn(name="Changed"))
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == "Original"
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 0
    monkeypatch.setattr(collections_service, "log_action", original)
    with TestSessionLocal() as db:
        collections_service.update_brand(None, db, bid, BrandIn(name="Changed"))
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == "Changed"
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 1


def test_exact_unique_constraint_rollback_does_not_add_audit():
    bid = seed_brand("Original")
    seed_brand("Taken")
    with TestSessionLocal() as db:
        with pytest.raises(IntegrityError):
            collections_service.update_brand(None, db, bid, BrandIn(name="Taken"))
        db.rollback()
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == "Original"
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 0


def test_authenticated_user_without_brand_permission_is_denied(client, auth_headers):
    bid = seed_brand()
    roles = client.get("/api/roles", headers=auth_headers).json()
    departments = client.get("/api/departments", headers=auth_headers).json()
    hr_role = next(role["id"] for role in roles if role["name"] == "HR")
    hr_dept = next(dept["id"] for dept in departments if dept["code"] == "HR")
    password = "BrandDenied!2026"
    created = client.post("/api/users", headers=auth_headers, json={
        "name": "Brand Denied", "email": "brand-denied@example.com", "password": password,
        "role_id": hr_role, "department_id": hr_dept})
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/token", data={"username": "brand-denied@example.com", "password": password})
    assert login.status_code == 200, login.text
    response = client.patch(f"/api/brands/{bid}", headers={"Authorization": f"Bearer {login.json()['access_token']}"}, json={"name": "Denied"})
    assert response.status_code == 403, response.text
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == "Original"
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 0


def test_service_passes_same_session_loaded_row_and_present_fields(monkeypatch):
    bid = seed_brand()
    original = collections_service.apply_brand_update
    seen = []
    def spy(db, brand, fields):
        assert object_session(brand) is db
        seen.append((db, brand, dict(fields)))
        original(db, brand, fields)
    monkeypatch.setattr(collections_service, "apply_brand_update", spy)
    with TestSessionLocal() as db:
        row = collections_service.update_brand(None, db, bid, BrandIn(name="Updated", description=None))
        assert seen == [(db, row, {"name": "Updated", "description": None})]


def test_brand_only_role_can_patch(client, auth_headers):
    bid = seed_brand()
    role = client.post("/api/roles", headers=auth_headers, json={"name": "BrandOnly", "permissions": ["modeling.brands"]})
    assert role.status_code == 201, role.text
    departments = client.get("/api/departments", headers=auth_headers)
    assert departments.status_code == 200, departments.text
    dept_id = next(dept["id"] for dept in departments.json() if dept["code"] == "HR")
    password = "BrandOnly!2026"
    created = client.post("/api/users", headers=auth_headers, json={"name": "Brand Only", "email": "brand-only@example.com", "password": password, "role_id": role.json()["id"], "department_id": dept_id})
    assert created.status_code == 201, created.text
    login = client.post("/api/auth/token", data={"username": "brand-only@example.com", "password": password})
    assert login.status_code == 200, login.text
    response = client.patch(f"/api/brands/{bid}", headers={"Authorization": f"Bearer {login.json()['access_token']}"}, json={"name": "Allowed"})
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        assert db.get(Brand, bid).name == "Allowed"
        assert db.query(AuditLog).filter_by(entity_type="Brand", entity_id=bid, action="update").count() == 1
