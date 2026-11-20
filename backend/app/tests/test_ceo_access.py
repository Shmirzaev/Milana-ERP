from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.ceo_access import CEO_DASHBOARD_ONLY_DETAIL, CEO_ROLE_NAME
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.core.signing import sign_path
from app.schemas import Role, User
from app.tests.conftest import TestSessionLocal

PASSWORD = "SyntheticCeoAccount!2026"
REPORT_PATH = "/api/dashboard/ceo?start=2026-01-08&end=2026-01-08"


def _account(role_name, *, permissions=None, factory="MIL", access_policy=None):
    with TestSessionLocal() as db:
        role = db.query(Role).filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name, permissions=[])
            db.add(role)
            db.flush()
        email = f"{role.name.lower().replace(' ', '-')}@ceo-test.example.com"
        account = User(
            name="Synthetic account", email=email, password_hash=hash_password(PASSWORD),
            role_id=role.id, factory_code=factory, extra_permissions=permissions or [],
            access_policy=access_policy, is_active=True,
        )
        db.add(account)
        db.commit()
        return account.id, email


def _bearer(user_id, **claims):
    return {"Authorization": f"Bearer {create_access_token(user_id, extra=claims)}"}


@pytest.mark.parametrize("role", ["Admin", "Wildcard", "Management", "ceo"])
def test_report_refuses_ordinary_roles_even_with_forged_ceo_claim(client, role):
    user_id, _ = _account(role, permissions=["*"] if role == "Wildcard" else [])
    assert client.get(REPORT_PATH, headers=_bearer(user_id, role=CEO_ROLE_NAME)).status_code == 403
    assert client.get(REPORT_PATH).status_code == 401


@pytest.mark.parametrize("role,permissions,policy,allowed", [
    ("Super Admin", [], None, True),
    ("Admin", ["admin.super"], None, True),
    ("Admin", [], {"MIL": {"allow": ["admin.super"]}}, True),
    ("Super Admin", ["*"], {"MIL": {"deny": ["admin.super"]}}, False),
    ("Admin", ["admin.super"], {"MIL": {"deny": ["admin.super"]}}, False),
    ("Admin", ["*"], None, False),
])
def test_report_superadmin_access_matches_server_identity(client, role, permissions, policy, allowed):
    user_id, _ = _account(role, permissions=permissions, access_policy=policy)
    headers = _bearer(user_id)
    identity = client.get("/api/auth/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["can_view_ceo_dashboard"] is allowed
    report = client.get(REPORT_PATH, headers=headers)
    assert report.status_code == (200 if allowed else 403), report.text
    if allowed:
        assert report.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_superadmin_retains_operations_and_all_factory_report_filters(client, factory):
    user_id, _ = _account("Super Admin", permissions=["*", "admin.super"])
    headers = _bearer(user_id, factory_code=factory)
    identity = client.get("/api/session/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["role"] == "Super Admin"
    assert identity.json()["factory_code"] == factory
    assert identity.json()["can_view_ceo_dashboard"] is True
    assert client.get("/api/users", headers=headers).status_code == 200
    for report_factory in ("ALL", "MIL", "BST", "ECO"):
        response = client.get(f"{REPORT_PATH}&factory={report_factory}", headers=headers)
        assert response.status_code == 200, response.text
    assert client.post(REPORT_PATH, headers=headers).status_code == 405


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_superadmin_factory_switch_keeps_report_access(client, transport):
    user_id, email = _account("Super Admin", permissions=["*", "admin.super"])
    headers = _bearer(user_id) if transport == "bearer" else {}
    if transport == "cookie":
        login = client.post("/api/auth/login-json", json={
            "email": email, "password": PASSWORD, "factory_code": "MIL",
        })
        assert login.status_code == 200, login.text
    for factory in ("BST", "ECO", "MIL"):
        switched = client.post("/api/session/switch-factory", headers=headers, json={"factory_code": factory})
        assert switched.status_code == 200, switched.text
        # Switching issues a new cookie, including when the request used bearer auth.
        identity = client.get("/api/session/me")
        assert identity.status_code == 200, identity.text
        assert identity.json()["factory_code"] == factory
        assert identity.json()["can_view_ceo_dashboard"] is True
        assert client.get(REPORT_PATH).status_code == 200
        assert client.get("/api/users").status_code == 200


def test_superadmin_primary_policy_revocation_applies_to_same_selected_factory_token(client):
    user_id, _ = _account("Super Admin", permissions=["*", "admin.super", "factory:ECO:storage.items"])
    headers = _bearer(user_id, factory_code="ECO")
    assert client.get(REPORT_PATH, headers=headers).status_code == 200
    with TestSessionLocal() as db:
        account = db.get(User, user_id)
        account.access_policy = {"MIL": {"deny": ["admin.super"]}}
        db.commit()
    identity = client.get("/api/session/me", headers=headers)
    assert identity.status_code == 200, identity.text
    assert identity.json()["factory_code"] == "ECO"
    assert identity.json()["can_view_ceo_dashboard"] is False
    assert client.get(REPORT_PATH, headers=headers).status_code == 403
    with TestSessionLocal() as db:
        db.get(User, user_id).extra_permissions = ["*", "admin.super"]
        db.commit()
    # Without a remaining ECO grant, existing factory-scope policy rejects the whole session.
    assert client.get("/api/session/me", headers=headers).status_code == 403
    assert client.get(REPORT_PATH, headers=headers).status_code == 403


@pytest.mark.parametrize("transport", ["cookie", "bearer"])
def test_ceo_session_has_no_operational_access_even_with_grants(client, transport):
    user_id, email = _account(
        CEO_ROLE_NAME, permissions=["*", "admin.super", "factory:MIL:finance.view"], factory="ECO",
        access_policy={"ECO": {"allow": ["*", "admin.super"]}},
    )
    headers = {}
    if transport == "cookie":
        login = client.post("/api/auth/login-json", json={"email": email, "password": PASSWORD, "factory_code": "MIL"})
        assert login.status_code == 200, login.text
        assert settings.AUTH_COOKIE_NAME in client.cookies
    else:
        machine_login = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
        assert machine_login.status_code == 200, machine_login.text
        headers = {"Authorization": f"Bearer {machine_login.json()['access_token']}"}

    for prefix in ("/api/auth", "/api/session"):
        identity = client.get(f"{prefix}/me", headers=headers)
        assert identity.status_code == 200, identity.text
        assert identity.headers["cache-control"] == "private, no-store"
        assert identity.json()["id"] == user_id
        assert identity.json()["role"] == CEO_ROLE_NAME
        assert identity.json()["can_view_ceo_dashboard"] is True
        assert identity.json()["permissions"] == identity.json()["extra_permissions"] == []
        assert identity.json()["available_factories"] == ["ECO"]
        for method, suffix, payload in (
            ("PATCH", "me", {"name": "Changed", "email": email}),
            ("POST", "switch-factory", {"factory_code": "MIL"}),
        ):
            refused = client.request(method, f"{prefix}/{suffix}", json=payload, headers=headers)
            assert (refused.status_code, refused.json()) == (403, {"detail": CEO_DASHBOARD_ONLY_DETAIL})

    for factory in ("ALL", "MIL", "BST", "ECO"):
        report = client.get(f"{REPORT_PATH}&factory={factory}", headers=headers)
        assert report.status_code == 200, report.text
        assert report.headers["cache-control"] == "private, no-store"
    assert client.post(REPORT_PATH, headers=headers).status_code == 405

    for method, path in (
        ("GET", "/api/settings"),
        ("GET", "/api/notifications"),
        ("GET", "/api/roles"),
        ("GET", "/api/users"),
        ("GET", "/api/dashboard/cutting?start=2026-01-08&end=2026-01-08"),
        ("GET", "/api/barcode/bundle/synthetic"),
        ("GET", "/storage/model-files/synthetic.png"),
        ("GET", "/storage/model-files/thumb/synthetic.png"),
        ("POST", "/api/notifications/read-all"),
    ):
        refused = client.request(method, path, headers=headers)
        assert (refused.status_code, refused.json()) == (403, {"detail": CEO_DASHBOARD_ONLY_DETAIL}), path

    change = client.post("/api/session/change-password", headers=headers, json={
        "current_password": PASSWORD, "new_password": "SyntheticCeoChanged!2026",
        "confirm_new_password": "SyntheticCeoChanged!2026",
    })
    assert change.status_code == 200, change.text
    assert client.get(REPORT_PATH, headers=headers).status_code == 401
    assert client.post("/api/session/logout", headers=headers).status_code == 200


def test_ceo_session_is_denied_legacy_operational_files(client, tmp_path, monkeypatch):
    from app import main

    name = "ceo-test-attachment.png"
    (tmp_path / name).write_bytes(b"synthetic attachment")
    monkeypatch.setattr(main, "_SALES_ORDER_FILES_ROOT", str(tmp_path))
    barcodes = Path(settings.BARCODE_STORAGE_DIR)
    barcode = barcodes / name
    barcode.write_bytes(b"synthetic barcode")
    user_id, _ = _account(CEO_ROLE_NAME)
    headers = _bearer(user_id)
    try:
        for path in (sign_path(f"/storage/sales-order-files/{name}"), f"/storage/barcodes/{name}"):
            assert client.get(path).status_code == 200
            response = client.get(path, headers=headers)
            assert (response.status_code, response.json()) == (403, {"detail": CEO_DASHBOARD_ONLY_DETAIL})
    finally:
        barcode.unlink()


def test_only_super_admin_can_assign_and_manage_ceo_role(client, auth_headers):
    lower_id, _ = _account("Admin")
    ceo_id, _ = _account(CEO_ROLE_NAME)
    worker_id, _ = _account("Warehouse Worker")
    lower_headers = _bearer(lower_id)
    worker_headers = _bearer(worker_id)
    with TestSessionLocal() as db:
        ceo_role = db.query(Role).filter_by(name=CEO_ROLE_NAME).one()
        assert ceo_role.permissions == []
        ceo_role_id = ceo_role.id
    new_ceo = {
        "name": "New Executive", "email": "new-executive@ceo-test.example.com",
        "password": PASSWORD, "role_id": ceo_role_id,
    }
    assert client.post("/api/users", headers=lower_headers, json=new_ceo).status_code == 403
    for name in ("CEO", "ceo", " CEO "):
        assert client.post("/api/roles", headers=auth_headers, json={"name": name}).status_code == 403
    assert client.patch(f"/api/users/{ceo_id}", headers=lower_headers, json={"password": PASSWORD}).status_code == 403
    assert client.patch(f"/api/users/{ceo_id}", headers=lower_headers, json={"email": "changed@ceo-test.example.com"}).status_code == 403
    assert client.delete(f"/api/users/{ceo_id}", headers=lower_headers).status_code == 403
    assert client.patch(f"/api/users/{worker_id}", headers=lower_headers, json={"role_id": ceo_role_id}).status_code == 403
    assert client.post("/api/users", headers=auth_headers, json=new_ceo).status_code == 201

    assert client.get(REPORT_PATH, headers=worker_headers).status_code == 403
    assert client.patch(f"/api/users/{worker_id}", headers=auth_headers, json={"role_id": ceo_role_id}).status_code == 200
    assert client.get(REPORT_PATH, headers=worker_headers).status_code == 401
    renewed_headers = _bearer(worker_id)
    assert client.get(REPORT_PATH, headers=renewed_headers).status_code == 200
    assert client.patch(f"/api/users/{worker_id}", headers=auth_headers, json={"role_id": None}).status_code == 200
    assert client.get(REPORT_PATH, headers=renewed_headers).status_code == 401
    assert client.get(REPORT_PATH, headers=_bearer(worker_id)).status_code == 403


@pytest.mark.parametrize("flow", ["login", "switch"])
def test_in_flight_session_issuance_cannot_bypass_ceo_role_cutoff(client, monkeypatch, flow):
    from app.api.routes import auth

    worker_id, email = _account("Warehouse Worker")
    operation = "login_user" if flow == "login" else "select_session_factory"
    original = getattr(auth, operation)

    def assign_ceo_before_issuance(*args, **kwargs):
        result = original(*args, **kwargs)
        with TestSessionLocal() as db:
            user = db.get(User, worker_id)
            user.role_id = db.query(Role.id).filter_by(name=CEO_ROLE_NAME).scalar()
            user.tokens_valid_from = datetime.now(timezone.utc)
            db.commit()
        return result

    monkeypatch.setattr(auth, operation, assign_ceo_before_issuance)
    if flow == "login":
        issuance = client.post("/api/auth/login-json", json={"email": email, "password": PASSWORD, "factory_code": "MIL"})
    else:
        issuance = client.post("/api/auth/switch-factory", headers=_bearer(worker_id), json={"factory_code": "MIL"})
    assert issuance.status_code == 200, issuance.text
    assert settings.AUTH_COOKIE_NAME in client.cookies
    assert client.get(REPORT_PATH).status_code == 401
