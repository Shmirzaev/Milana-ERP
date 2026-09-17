import ast
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.deps import is_admin, is_super_admin, user_permissions
from app.core.permission_catalog import PERMISSION_KEYS
from app.services.factory_scope import available_factory_codes, authorize_login_factory
from app.services.price_calculation import is_accessory_pricing_user, is_price_purchaser


def subject(permissions=None, policy=None, role="Planning", factory="MIL", extra=None):
    return SimpleNamespace(
        name="Test", email="test@example.com", role=SimpleNamespace(name=role, permissions=permissions or []),
        department=SimpleNamespace(code="PLN"), factory_code=factory,
        extra_permissions=extra or [], access_policy=policy,
    )


def test_legacy_permissions_are_unchanged_without_policy():
    u = subject(["planning.view", "planning.production"], extra=["finance.view", "factory:ECO:cutting.records"])
    assert user_permissions(u) == ["planning.view", "planning.production", "finance.view"]
    u.session_factory_code = "ECO"
    assert user_permissions(u) == ["cutting.records"]


def test_deny_wins_over_role_and_legacy_extra_without_changing_role():
    u = subject(["sales.orders", "sales.customers"], {"MIL": {"deny": ["sales.orders"], "allow": ["finance.view"]}}, extra=["sales.orders"])
    assert set(user_permissions(u)) == {"sales.customers", "finance.view"}
    assert u.role.permissions == ["sales.orders", "sales.customers"]


def test_wildcard_and_admin_name_do_not_bypass_denials():
    u = subject(["*"], {"MIL": {"deny": ["finance.view"]}}, role="Admin")
    assert "finance.view" not in user_permissions(u)
    assert "sales.orders" in user_permissions(u)
    assert "*" not in user_permissions(u)
    assert not is_admin(u)
    assert not is_super_admin(u)


def test_factory_overrides_never_leak_primary_role():
    u = subject(["planning.production"], {"ECO": {"allow": ["cutting.records"], "deny": ["usluga.manage"]}}, extra=["factory:ECO:usluga.manage"])
    assert available_factory_codes(u) == ["MIL", "ECO"]
    assert authorize_login_factory(u, "ECO") == "ECO"
    u.session_factory_code = "ECO"
    assert user_permissions(u) == ["cutting.records"]
    u.access_policy = {"ECO": {"deny": ["usluga.manage"]}}
    assert available_factory_codes(u) == ["MIL"]
    with pytest.raises(Exception) as error:
        authorize_login_factory(u, "ECO")
    assert error.value.status_code == 403


def test_department_pricing_can_be_revoked_without_identity_grants():
    u = subject(["storage.items"], {"MIL": {"deny": ["price_calculation.purchasing", "price_calculation.accessories"]}})
    u.name = "Abbosbek"
    u.department.code = "STR"
    assert not is_price_purchaser(u)
    assert not is_accessory_pricing_user(u)
    u.access_policy = None
    assert not is_price_purchaser(u)
    assert is_accessory_pricing_user(u)
    u.extra_permissions = ["price_calculation.purchasing"]
    assert is_price_purchaser(u)


def test_catalog_covers_authorization_keys():
    root = Path(__file__).parents[1]
    roots = {key.split(".")[0] for key in PERMISSION_KEYS if "." in key}
    found = set()
    for folder in ["api", "services", "core", "db"]:
        for path in (root / folder).rglob("*.py"):
            if path.name == "permission_catalog.py":
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "require_permissions":
                    found.update(arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str))
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    key = node.value
                    if re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)+", key) and key.split(".")[0] in roots:
                        found.add(key)
    assert not (found - PERMISSION_KEYS), f"Add administration controls for {sorted(found - PERMISSION_KEYS)}"


def create(client, headers, **values):
    return client.post("/api/users", headers=headers, json={"name": "Policy Test", "email": "policy@example.com", "password": "PolicyTest!2026", **values})


def login(client, email="policy@example.com"):
    response = client.post("/api/auth/token", data={"username": email, "password": "PolicyTest!2026"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_create_edit_and_revoke_use_existing_session(client, auth_headers):
    roles = client.get("/api/roles", headers=auth_headers).json()
    role = next(r for r in roles if r["name"] == "Planning")
    response = create(client, auth_headers, role_id=role["id"], access_policy={"MIL": {"allow": ["finance.view"], "deny": ["planning.production"]}})
    assert response.status_code == 201, response.text
    user_id = response.json()["id"]
    headers = login(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["access_configured"]
    assert "finance.view" in me["permissions"] and "planning.production" not in me["permissions"]
    assert client.get("/api/finance/dashboard", headers=headers).status_code == 200
    changed = client.patch(f"/api/users/{user_id}", headers=auth_headers, json={"access_policy": {"MIL": {"deny": ["finance.view", "planning.production"]}}})
    assert changed.status_code == 200, changed.text
    assert client.get("/api/finance/dashboard", headers=headers).status_code == 403
    assert client.get("/api/roles", headers=auth_headers).json() == roles


@pytest.mark.parametrize("policy", [{"BAD": {"allow": ["finance.view"]}}, {"MIL": {"allow": ["made.up"]}}, {"MIL": {"allow": ["finance.view"], "deny": ["finance.view"]}}])
def test_invalid_policies_are_rejected(client, auth_headers, policy):
    assert create(client, auth_headers, access_policy=policy).status_code == 422


def test_limited_manager_cannot_escalate_by_allow_or_removing_deny(client, auth_headers):
    role = client.post("/api/roles", headers=auth_headers, json={"name": "PolicyManager", "permissions": ["admin.users"]}).json()
    assert create(client, auth_headers, role_id=role["id"]).status_code == 201
    manager = login(client)
    target = create(client, auth_headers, email="target@example.com", extra_permissions=["finance.view"], access_policy={"MIL": {"deny": ["finance.view"]}}).json()
    for policy in [{"MIL": {"allow": ["finance.view"]}}, {}, {"ECO": {"allow": ["cutting.records"]}}, {"MIL": {"allow": ["admin.super"]}}]:
        response = client.patch(f"/api/users/{target['id']}", headers=manager, json={"access_policy": policy})
        assert response.status_code == 403, response.text


def test_last_administrator_cannot_be_denied(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    response = client.patch(f"/api/users/{me['id']}", headers=auth_headers, json={"access_policy": {"MIL": {"deny": ["*", "admin.super"]}}})
    assert response.status_code == 400, response.text


def test_preview_does_not_create_or_change_users(client, auth_headers):
    before = client.get("/api/users", headers=auth_headers).json()
    response = client.post("/api/users/access-preview", headers=auth_headers, json={"name": "Preview", "email": "preview@example.com", "access_policy": {"ECO": {"allow": ["cutting.records"]}}})
    assert response.status_code == 200, response.text
    assert response.json()["ECO"] == {"permissions": ["cutting.records"], "effective": ["cutting.records"], "available": True}
    assert client.get("/api/users", headers=auth_headers).json() == before
    catalog = client.get("/api/access-catalog", headers=auth_headers).json()
    assert {p["key"] for p in catalog} == PERMISSION_KEYS
