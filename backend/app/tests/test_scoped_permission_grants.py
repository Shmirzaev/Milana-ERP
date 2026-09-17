from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import AuditLog, Role, User
from app.tests.conftest import TestSessionLocal


def _user(*, permissions=(), extra=(), policy=None, factory="MIL", selected=None, super_admin=False):
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        role = Role(
            name=f"Scoped grant {marker}",
            permissions=["*", "admin.super"] if super_admin else list(permissions),
        )
        user = User(
            name=f"Scoped user {marker}", email=f"scoped-{marker}@example.com",
            password_hash="unused-token-fixture", role=role, factory_code=factory,
            extra_permissions=list(extra), access_policy=policy,
        )
        db.add(user)
        db.commit()
        return user.id, {"Authorization": f"Bearer {create_access_token(user.id, extra={'factory_code': selected or factory})}"}


def _snapshot(target_id=None):
    with TestSessionLocal() as db:
        target = db.get(User, target_id) if target_id else None
        return (
            db.query(User).count(), db.query(Role).count(), db.query(AuditLog).count(),
            (target.role_id, target.extra_permissions, target.name) if target else None,
        )


def _create_payload(permissions):
    marker = uuid4().hex[:12]
    return {
        "name": "Scoped grant target", "email": f"grant-target-{marker}@example.com",
        "password": "ScopedGrant!2026", "factory_code": "MIL", "extra_permissions": permissions,
    }


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
@pytest.mark.parametrize("permission", ["*", "admin.super"], ids=["wildcard", "super-admin"])
def test_legacy_wildcard_cannot_create_scoped_administrator(client, factory, permission):
    _, headers = _user(permissions=["*"])
    before = _snapshot()
    response = client.post(
        "/api/users", headers=headers, json=_create_payload([f"factory:{factory}:{permission}"]),
    )
    assert response.status_code == 403, response.text
    assert _snapshot() == before


@pytest.mark.parametrize("factory", ["MIL", "ECO"])
@pytest.mark.parametrize("permission", ["*", "admin.super"], ids=["wildcard", "super-admin"])
def test_legacy_wildcard_cannot_add_scoped_administrator_access(client, factory, permission):
    _, headers = _user(permissions=["*"])
    target_id, _ = _user()
    before = _snapshot(target_id)
    response = client.patch(
        f"/api/users/{target_id}", headers=headers,
        json={"extra_permissions": [f"factory:{factory}:{permission}"]},
    )
    assert response.status_code == 403, response.text
    assert _snapshot(target_id) == before


@pytest.mark.parametrize("operation", ["create", "assign", "assign_new_user"])
@pytest.mark.parametrize("permission", ["*", "admin.super"], ids=["wildcard", "super-admin"])
def test_role_vector_cannot_grant_scoped_administrator_access(client, operation, permission):
    _, headers = _user(permissions=["*"])
    target_id, _ = _user()
    role_data = {"name": f"Scoped role {uuid4().hex[:12]}", "permissions": [f"factory:MIL:{permission}"]}
    if operation != "create":
        with TestSessionLocal() as db:
            role = Role(**role_data)
            db.add(role)
            db.commit()
            role_id = role.id
    before = _snapshot(target_id)
    if operation == "create":
        response = client.post("/api/roles", headers=headers, json=role_data)
    elif operation == "assign_new_user":
        response = client.post("/api/users", headers=headers, json={**_create_payload([]), "role_id": role_id})
    else:
        response = client.patch(f"/api/users/{target_id}", headers=headers, json={"role_id": role_id})
    assert response.status_code == 403, response.text
    assert _snapshot(target_id) == before


@pytest.mark.parametrize("operation", ["create", "add", "remove"])
def test_scoped_changes_cannot_target_another_factory_even_if_actor_has_access(client, operation):
    token = "factory:ECO:finance.view"
    _, headers = _user(permissions=["*"], extra=[token])
    target_id, _ = _user(extra=[token] if operation == "remove" else [])
    before = _snapshot(target_id)
    response = (
        client.post("/api/users", headers=headers, json=_create_payload([token])) if operation == "create"
        else client.patch(
            f"/api/users/{target_id}", headers=headers,
            json={"extra_permissions": [] if operation == "remove" else [token]},
        )
    )
    assert response.status_code == 403, response.text
    assert _snapshot(target_id) == before


@pytest.mark.parametrize("primary_factory", ["ECO", "MIL"])
def test_selected_factory_can_delegate_an_effective_underlying_permission(client, primary_factory):
    _, headers = _user(
        permissions=["admin.users", "finance.view"] if primary_factory == "ECO" else [],
        extra=["factory:ECO:admin.users", "factory:ECO:finance.view"] if primary_factory == "MIL" else [],
        factory=primary_factory, selected="ECO",
    )
    target_id, primary_headers = _user()
    response = client.patch(
        f"/api/users/{target_id}", headers=headers,
        json={"extra_permissions": ["factory:ECO:finance.view"]},
    )
    assert response.status_code == 200, response.text
    eco_headers = {"Authorization": f"Bearer {create_access_token(target_id, extra={'factory_code': 'ECO'})}"}
    assert client.get("/api/auth/me", headers=eco_headers).json()["permissions"] == ["finance.view"]
    assert "finance.view" not in client.get("/api/auth/me", headers=primary_headers).json()["permissions"]
    assert client.get("/api/finance/dashboard", headers=eco_headers).status_code == 200
    assert client.get("/api/users", headers=eco_headers).status_code == 403


@pytest.mark.parametrize("denied", [False, True])
def test_underlying_permission_must_be_held_after_policy_denials(client, denied):
    _, headers = _user(
        permissions=["*"] if denied else ["admin.users"],
        policy={"MIL": {"deny": ["finance.view"]}} if denied else None,
    )
    target_id, _ = _user(factory="ECO")
    before = _snapshot(target_id)
    response = client.patch(
        f"/api/users/{target_id}", headers=headers,
        json={"extra_permissions": ["factory:MIL:finance.view"]},
    )
    assert response.status_code == 403, response.text
    assert _snapshot(target_id) == before


@pytest.mark.parametrize("include_unchanged_access", [False, True])
def test_profile_edit_retains_unchanged_foreign_scoped_tokens(client, include_unchanged_access):
    _, headers = _user(permissions=["admin.users"])
    original = ["factory:ECO:*", "factory:ECO:finance.view"]
    target_id, _ = _user(extra=original)
    payload = {"name": "Renamed without access changes"}
    if include_unchanged_access:
        payload["extra_permissions"] = original
    response = client.patch(f"/api/users/{target_id}", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["extra_permissions"] == original


def test_selected_factory_can_remove_existing_scoped_permission(client):
    _, headers = _user(permissions=["admin.users"])
    target_id, _ = _user(factory="ECO", extra=["factory:MIL:finance.view"])
    response = client.patch(f"/api/users/{target_id}", headers=headers, json={"extra_permissions": []})
    assert response.status_code == 200, response.text
    assert response.json()["extra_permissions"] == []


@pytest.mark.parametrize("operation", ["create_user", "update_user", "create_role", "assign_role"])
def test_super_admin_can_grant_scoped_access_through_existing_vectors(client, operation):
    _, headers = _user(super_admin=True)
    permissions = ["factory:ECO:*", "factory:ECO:admin.super"]
    target_id, _ = _user()
    if operation == "create_user":
        response = client.post("/api/users", headers=headers, json=_create_payload(permissions))
    elif operation == "update_user":
        response = client.patch(f"/api/users/{target_id}", headers=headers, json={"extra_permissions": permissions})
    elif operation == "create_role":
        response = client.post("/api/roles", headers=headers, json={"name": f"Super scoped {uuid4().hex[:12]}", "permissions": permissions})
    else:
        with TestSessionLocal() as db:
            role = Role(name=f"Existing scoped {uuid4().hex[:12]}", permissions=permissions)
            db.add(role)
            db.commit()
            role_id = role.id
        response = client.patch(f"/api/users/{target_id}", headers=headers, json={"role_id": role_id})
    assert response.status_code == (201 if operation in {"create_user", "create_role"} else 200), response.text
