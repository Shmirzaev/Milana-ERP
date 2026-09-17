"""SEC01: grant checks must inspect legacy factory wrappers before '*' shortcuts."""
import pytest

from app.core.security import hash_password
from app.models import Role, User
from app.tests.conftest import TestSessionLocal


def manager_headers(client, permissions):
    with TestSessionLocal() as db:
        role = Role(name="Scoped grant manager", permissions=permissions)
        db.add(role)
        db.flush()
        db.add(User(name="Grant manager", email="grant-manager@example.com",
                    password_hash=hash_password("GrantManager!2026"), role_id=role.id,
                    factory_code="MIL", is_active=True))
        db.commit()
    response = client.post("/api/auth/token", data={
        "username": "grant-manager@example.com", "password": "GrantManager!2026"})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def create(client, headers, **values):
    return client.post("/api/users", headers=headers, json={
        "name": "Grant target", "email": "grant-target@example.com",
        "password": "GrantTarget!2026", **values})


@pytest.mark.parametrize("token", ["factory:ECO:*", "factory:MIL:*", "factory:ECO:finance.view"])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_wildcard_manager_cannot_bypass_grant_restrictions(client, auth_headers, token, operation):
    target = create(client, auth_headers).json() if operation == "update" else None
    headers = manager_headers(client, ["*"])
    if target:
        response = client.patch(f"/api/users/{target['id']}", headers=headers,
                                json={"extra_permissions": [token]})
    else:
        response = create(client, headers, extra_permissions=[token])
    assert response.status_code == 403, response.text
    with TestSessionLocal() as db:
        user = db.query(User).filter(User.email == "grant-target@example.com").first()
        assert user is None or not user.extra_permissions


@pytest.mark.parametrize("token", ["factory:ECO:admin.super", "factory:BAD:finance.view",
                                    "factory:ECO:factory:MIL:*", "factory:ECO:made.up", "made.up"])
def test_invalid_grants_rejected_even_for_super_admin(client, auth_headers, token):
    response = create(client, auth_headers, extra_permissions=[token])
    assert response.status_code == 400, response.text


def test_super_admin_can_grant_canonical_secondary_access(client, auth_headers):
    response = create(client, auth_headers, extra_permissions=[" factory: eco : * ", "factory:ECO:*"])
    assert response.status_code == 201, response.text
    assert response.json()["extra_permissions"] == ["factory:ECO:*"]
    login = client.post("/api/auth/login-json", json={"email": "grant-target@example.com",
                                               "password": "GrantTarget!2026", "factory_code": "ECO"})
    assert login.status_code == 200, login.text
    me = client.get("/api/auth/me").json()
    assert me["factory_code"] == "ECO"
    assert "*" in me["permissions"]
    assert client.get("/api/users").status_code == 200


def test_limited_manager_can_grant_only_owned_permission_in_selected_factory(client, auth_headers):
    target = create(client, auth_headers).json()
    headers = manager_headers(client, ["admin.users", "finance.view"])
    endpoint = f"/api/users/{target['id']}"
    allowed = client.patch(endpoint, headers=headers, json={"extra_permissions": ["factory:MIL:finance.view"]})
    assert allowed.status_code == 200, allowed.text
    denied = client.patch(endpoint, headers=headers, json={"extra_permissions": ["factory:MIL:planning.view"]})
    assert denied.status_code == 403, denied.text


@pytest.mark.parametrize("operation", ["create_role", "assign_role"])
def test_factory_tokens_cannot_be_smuggled_through_global_roles(client, auth_headers, operation):
    if operation == "create_role":
        response = client.post("/api/roles", headers=auth_headers,
                               json={"name": "Invalid scoped role", "permissions": ["factory:ECO:*"]})
    else:
        with TestSessionLocal() as db:
            role = Role(name="Legacy scoped role", permissions=["factory:ECO:*"])
            db.add(role)
            db.commit()
            role_id = role.id
        response = create(client, auth_headers, role_id=role_id)
    assert response.status_code == 400, response.text
