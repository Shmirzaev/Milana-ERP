"""Profile-update contract before its Identity service move."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.main import app
from app.schemas import AuditLog, Role, User
from app.tests.test_auth_login_characterization import login_database as login_database


@pytest.fixture
def h(login_database):
    factory = login_database
    marker = uuid4().hex
    with factory() as db:
        role = Role(name=f"Profile baseline {marker}", permissions=["finance.view"])
        db.add(role)
        db.flush()
        user = User(name="Old name", email=f"profile-{marker}@example.com",
                    password_hash=hash_password("ProfileBaseline!2026"), role_id=role.id,
                    factory_code="MIL", is_active=True)
        other = User(name="Other", email=f"other-{marker}@example.com",
                     password_hash=hash_password("ProfileBaseline!2026"), factory_code="MIL", is_active=True)
        db.add_all([user, other])
        db.commit()
        user_id, email, other_email, role_name = user.id, user.email, other.email, role.name

    def sessions():
        with factory() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = sessions
    try:
        yield factory, user_id, email, other_email, role_name, TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides[get_db] = previous


def state(h):
    factory, user_id, *_ = h
    with factory() as db:
        user = db.get(User, user_id)
        audits = db.query(AuditLog).filter_by(user_id=user_id, action="update_profile").all()
        return user.name, user.email, user.last_seen_at, len(audits)


@pytest.mark.parametrize("path,transport", [
    ("/api/auth/me", "bearer"), ("/api/session/me", "cookie"),
])
def test_update_normalizes_and_audits_once_without_last_seen(path, transport, h):
    factory, user_id, email, _, role_name, client = h
    token = create_access_token(user_id, {"factory_code": "MIL"})
    headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    before = state(h)
    response = client.patch(path, json={"name": "  New name  ", "email": email.upper()}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sewing_band_id": None, "id": user_id, "name": "New name", "email": email,
        "role": role_name, "department": None, "department_code": None,
        "extra_permissions": [], "permissions": ["finance.view"],
        "factory_code": "MIL", "assigned_factory_code": "MIL",
        "available_factories": ["MIL"], "access_configured": False,
    }
    assert state(h) == ("New name", email, before[2], before[3] + 1)
    with factory() as db:
        audit = db.query(AuditLog).filter_by(user_id=user_id, action="update_profile").one()
        assert audit.old_value_json == {"name": "Old name", "email": email}
        assert audit.new_value_json == {"name": "New name", "email": email}


@pytest.mark.parametrize("case,status,detail", [
    ("name_too_long", 422, "Name must be at most 128 characters"),
    # Decision (Dilmurod, 5 Nov): profile email is immutable, including duplicates.
    ("duplicate_email", 400, "Email cannot be changed from Profile"),
    ("inactive", 401, "Inactive or unknown user"),
    ("unassigned", 403, "This account is not assigned to the selected factory"),
    ("missing", 401, "Not authenticated"),
])
def test_refusal_order_and_no_writes(case, status, detail, h):
    factory, user_id, email, other_email, _, client = h
    if case == "inactive":
        with factory() as db:
            db.get(User, user_id).is_active = False
            db.commit()
    token = create_access_token(user_id, {"factory_code": "BST" if case == "unassigned" else "MIL"})
    headers = {} if case == "missing" else {"Authorization": f"Bearer {token}"}
    payload = {"name": "x" * 129 if case == "name_too_long" else "Changed",
               "email": other_email if case in {"name_too_long", "duplicate_email"} else email}
    before = state(h)
    response = client.patch("/api/auth/me", json=payload, headers=headers)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert state(h) == before


@pytest.mark.parametrize("path,transport", [
    ("/api/auth/me", "bearer"), ("/api/session/me", "cookie"),
])
def test_self_email_change_refused_without_name_or_audit_write(path, transport, h):
    _, user_id, email, _, _, client = h
    token = create_access_token(user_id, {"factory_code": "MIL"})
    headers = {"Authorization": f"Bearer {token}"} if transport == "bearer" else {}
    if transport == "cookie":
        client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    before = state(h)
    changed = f"changed-{email}"
    response = client.patch(path, headers=headers, json={"name": "Unauthorized rename", "email": changed})
    assert (response.status_code, response.json()) == (400, {"detail": "Email cannot be changed from Profile"})
    assert state(h) == before


def test_admin_users_still_changes_another_users_email(h):
    factory, user_id, email, _, _, client = h
    with factory() as db:
        role = Role(name=f"Email manager {uuid4().hex}", permissions=["admin.users"])
        db.add(role)
        db.flush()
        admin = User(name="Email manager", email=f"manager-{uuid4().hex}@example.com",
                     password_hash=hash_password("EmailManager!2026"), role_id=role.id,
                     factory_code="MIL", is_active=True)
        db.add(admin)
        db.commit()
        admin_id = admin.id
    changed = f"new-{email}"
    response = client.patch(f"/api/users/{user_id}",
                            headers={"Authorization": f"Bearer {create_access_token(admin_id)}"},
                            json={"email": changed})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == changed
    with factory() as db:
        assert db.get(User, user_id).email == changed
