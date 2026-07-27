"""Regression tests for the security fixes:
- H1: privilege escalation via user/role management
- H2: state-changing endpoints gated by permission, not just login
- M2: password change/reset invalidates existing tokens
"""

import base64
import os
import time

STRONG_PW = "Str0ngManager!2026"
ESC_PW = "Esc4lation!Test2026"


def _login(client, email, password):
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _role_id(client, auth_headers, name):
    r = client.get("/api/roles", headers=auth_headers)
    assert r.status_code == 200, r.text
    for role in r.json():
        if role["name"] == name:
            return role["id"]
    return None


def _dept_id(client, auth_headers, code):
    r = client.get("/api/departments", headers=auth_headers)
    assert r.status_code == 200, r.text
    return next(d["id"] for d in r.json() if d["code"] == code)


# ---------- H1: privilege escalation ----------

def test_user_manager_cannot_assign_admin_role(client, auth_headers):
    admin_role_id = _role_id(client, auth_headers, "Admin")
    hr_dept = _dept_id(client, auth_headers, "HR")

    # Superadmin mints a limited "user manager" role holding only admin.users.
    r = client.post(
        "/api/roles",
        json={"name": "UserManager", "permissions": ["admin.users"]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    manager_role_id = r.json()["id"]

    r = client.post(
        "/api/users",
        json={
            "name": "Limited Manager",
            "email": "limited.manager@example.com",
            "password": STRONG_PW,
            "role_id": manager_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    manager_id = r.json()["id"]

    mgr_headers = _login(client, "limited.manager@example.com", STRONG_PW)

    # Creating a new user with the admin ('*') role must be refused.
    r = client.post(
        "/api/users",
        json={
            "name": "Sneaky Admin",
            "email": "sneaky.admin@example.com",
            "password": ESC_PW,
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=mgr_headers,
    )
    assert r.status_code == 403, r.text

    # Self-escalation to the admin role must be refused.
    r = client.patch(
        f"/api/users/{manager_id}",
        json={"role_id": admin_role_id},
        headers=mgr_headers,
    )
    assert r.status_code == 403, r.text

    # Changing one's own role at all is refused for a non-superadmin.
    r = client.patch(
        f"/api/users/{manager_id}",
        json={"role_id": admin_role_id},
        headers=mgr_headers,
    )
    assert r.status_code == 403, r.text


def test_admin_can_still_assign_roles(client, auth_headers):
    """The guard must not break legitimate superadmin user management."""
    cutting_role_id = _role_id(client, auth_headers, "Cutting")
    cut_dept = _dept_id(client, auth_headers, "CUT")
    r = client.post(
        "/api/users",
        json={
            "name": "Floor Worker",
            "email": "floor.worker@example.com",
            "password": STRONG_PW,
            "role_id": cutting_role_id,
            "department_id": cut_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text


def test_regular_admin_cannot_assign_or_remove_admins(client, auth_headers):
    admin_role_id = _role_id(client, auth_headers, "Admin")
    hr_role_id = _role_id(client, auth_headers, "HR")
    hr_dept = _dept_id(client, auth_headers, "HR")
    regular_admin_password = "RegularAdmin!2026"
    protected_admin_password = "ProtectedAdmin!2026"

    r = client.post(
        "/api/users",
        json={
            "name": "Regular Admin",
            "email": "regular.admin@example.com",
            "password": regular_admin_password,
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/users",
        json={
            "name": "Protected Admin",
            "email": "protected.admin@example.com",
            "password": protected_admin_password,
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    protected_admin_id = r.json()["id"]

    admin_headers = _login(client, "regular.admin@example.com", regular_admin_password)

    r = client.post(
        "/api/roles",
        json={"name": "ShadowFullAdmin", "permissions": ["*"]},
        headers=admin_headers,
    )
    assert r.status_code == 403, r.text

    r = client.post(
        "/api/roles",
        json={"name": "ShadowSuperAdmin", "permissions": ["admin.super"]},
        headers=admin_headers,
    )
    assert r.status_code == 403, r.text

    r = client.post(
        "/api/users",
        json={
            "name": "Admin Created By Admin",
            "email": "admin.created.by.admin@example.com",
            "password": ESC_PW,
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=admin_headers,
    )
    assert r.status_code == 403, r.text

    r = client.patch(f"/api/users/{protected_admin_id}", json={"role_id": hr_role_id}, headers=admin_headers)
    assert r.status_code == 403, r.text

    r = client.patch(
        f"/api/users/{protected_admin_id}",
        json={"password": "ResetProtected!2026"},
        headers=admin_headers,
    )
    assert r.status_code == 403, r.text

    r = client.patch(f"/api/users/{protected_admin_id}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 403, r.text

    r = client.delete(f"/api/users/{protected_admin_id}", headers=admin_headers)
    assert r.status_code == 403, r.text


def test_super_admin_can_assign_and_remove_admin_role(client, auth_headers):
    admin_role_id = _role_id(client, auth_headers, "Admin")
    hr_role_id = _role_id(client, auth_headers, "HR")
    hr_dept = _dept_id(client, auth_headers, "HR")

    r = client.post(
        "/api/users",
        json={
            "name": "Promoted Admin",
            "email": "promoted.admin@example.com",
            "password": "PromotedAdmin!2026",
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    promoted_admin_id = r.json()["id"]

    r = client.patch(f"/api/users/{promoted_admin_id}", json={"role_id": hr_role_id}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["role_id"] == hr_role_id

    r = client.post(
        "/api/users",
        json={
            "name": "Removed Admin",
            "email": "removed.admin@example.com",
            "password": "RemovedAdmin!2026",
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.delete(f"/api/users/{r.json()['id']}", headers=auth_headers)
    assert r.status_code == 204, r.text


def test_super_data_console_requires_true_super_admin(client, auth_headers):
    r = client.get("/api/admin/super-data/tables", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(table["name"] == "users" for table in r.json())

    admin_role_id = _role_id(client, auth_headers, "Admin")
    hr_dept = _dept_id(client, auth_headers, "HR")
    password = "DataConsoleAdmin!2026"
    r = client.post(
        "/api/users",
        json={
            "name": "Data Console Regular Admin",
            "email": "data.console.regular.admin@example.com",
            "password": password,
            "role_id": admin_role_id,
            "department_id": hr_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    regular_admin_headers = _login(client, "data.console.regular.admin@example.com", password)
    r = client.get("/api/admin/super-data/tables", headers=regular_admin_headers)
    assert r.status_code == 403, r.text


def test_super_admin_can_edit_and_delete_rows_from_super_data_console(client, auth_headers):
    r = client.post(
        "/api/departments",
        json={"name": "Super Data Temporary", "code": "SDC"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    department_id = r.json()["id"]

    r = client.patch(
        f"/api/admin/super-data/tables/departments/rows/{department_id}",
        json={"values": {"name": "Super Data Edited"}},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Super Data Edited"

    r = client.get("/api/admin/super-data/tables/departments?q=Super%20Data%20Edited", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(row["id"] == department_id for row in r.json()["rows"])

    r = client.delete(f"/api/admin/super-data/tables/departments/rows/{department_id}", headers=auth_headers)
    assert r.status_code == 204, r.text

    r = client.get("/api/admin/super-data/tables/departments?q=Super%20Data%20Edited", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert not any(row["id"] == department_id for row in r.json()["rows"])


# ---------- H2: permission gating on state changes ----------

def test_hr_user_cannot_post_quality_check(client, auth_headers):
    # hr@example.com has only hr.employees — no production permission.
    hr_headers = _login(client, "hr@example.com", "demo12345")
    r = client.post(
        "/api/quality/checks",
        json={"work_order_id": 999999, "checked_qty": 1, "passed_qty": 1, "failed_qty": 0},
        headers=hr_headers,
    )
    assert r.status_code == 403, r.text


def test_hr_user_cannot_start_work_order(client, auth_headers):
    hr_headers = _login(client, "hr@example.com", "demo12345")
    r = client.post("/api/work-orders/999999/start", headers=hr_headers)
    assert r.status_code == 403, r.text


def test_hr_user_cannot_read_protected_domain_endpoints(client):
    hr_headers = _login(client, "hr@example.com", "demo12345")
    endpoints = [
        "/api/inventory/items",
        "/api/production-orders",
        "/api/packages/999999/label",
        "/api/packages/label-sheet/by-ids?ids=999999",
        "/api/bundles/999999/label",
        "/api/bundles/label-sheet/by-ids?ids=999999",
        "/api/bundles/label-sheet/by-production-order/999999",
        "/api/bundles/label-sheet/by-batch/999999",
        "/api/traceability/export/package/999999",
        "/api/finance/waste-report",
        "/api/audit-logs/hash-chain/export",
        "/api/dashboard/inventory",
        "/api/customers",
        "/api/suppliers",
    ]

    for endpoint in endpoints:
        r = client.get(endpoint, headers=hr_headers)
        assert r.status_code == 403, endpoint

    post_endpoints = [
        "/api/barcode/generate-bundle-label/999999",
        "/api/barcode/generate-package-label/999999",
    ]
    for endpoint in post_endpoints:
        r = client.post(endpoint, headers=hr_headers)
        assert r.status_code == 403, endpoint


def test_hr_user_can_read_process_tracking(client):
    hr_headers = _login(client, "hr@example.com", "demo12345")

    listing = client.get("/api/process-tracking", headers=hr_headers)
    assert listing.status_code == 200, listing.text

    summary = client.get("/api/process-tracking/summary", headers=hr_headers)
    assert summary.status_code == 200, summary.text

    exported = client.get("/api/process-tracking/export", headers=hr_headers)
    assert exported.status_code == 200, exported.text
    assert "text/html" in exported.headers.get("content-type", "")


# ---------- M2: token invalidation on password change ----------

def test_password_change_invalidates_existing_token(client, auth_headers):
    fin_dept = _dept_id(client, auth_headers, "FIN")
    finance_role_id = _role_id(client, auth_headers, "Finance")
    r = client.post(
        "/api/users",
        json={
            "name": "Token Tester",
            "email": "token.tester@example.com",
            "password": STRONG_PW,
            "role_id": finance_role_id,
            "department_id": fin_dept,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    old_headers = _login(client, "token.tester@example.com", STRONG_PW)
    assert client.get("/api/auth/me", headers=old_headers).status_code == 200

    # JWT `iat` is second-resolution; ensure the change lands in a later second so
    # the previously issued token is strictly older than the new watermark.
    time.sleep(1.1)
    r = client.post(
        "/api/auth/change-password",
        json={
            "current_password": STRONG_PW,
            "new_password": ESC_PW,
            "confirm_new_password": ESC_PW,
        },
        headers=old_headers,
    )
    assert r.status_code == 200, r.text

    # The token issued before the password change is now rejected.
    assert client.get("/api/auth/me", headers=old_headers).status_code == 401
    # A fresh login works.
    new_headers = _login(client, "token.tester@example.com", ESC_PW)
    assert client.get("/api/auth/me", headers=new_headers).status_code == 200


# ---------- M1: signed URLs for sensitive sales-order attachments ----------

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_login_sets_httponly_cookie_and_cookie_auth_works(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "erp_access_token=" in set_cookie
    assert "httponly" in set_cookie

    # No Authorization header: TestClient sends the cookie it received above.
    assert client.get("/api/auth/me").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200, logout.text
    assert client.get("/api/auth/me").status_code == 401


def test_https_forwarded_login_cookie_is_secure(client):
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@example.com", "password": "test-admin-password-123!"},
        headers={"x-forwarded-proto": "https"},
    )
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "erp_access_token=" in set_cookie
    assert "secure" in set_cookie




def test_public_deployment_login_cookie_is_secure(client, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEPLOYMENT", "1")
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "erp_access_token=" in set_cookie
    assert "secure" in set_cookie


def test_password_reset_failure_notification_suppresses_token_like_error_text(client):
    from app.services.password_reset import notify_admins_about_password_email_failure
    from app.db.session import SessionLocal
    from app.models import Notification, User

    raw_url = "https://frontend.example/reset-password?token=raw-reset-token-should-not-persist"
    provider_error = f"provider echoed body containing {raw_url} and token=raw-reset-token-should-not-persist"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "admin@example.com").first()
        assert user is not None
        user_id = user.id
        before = db.query(Notification).filter(Notification.title == "Password reset email failed").count()
    finally:
        db.close()

    notify_admins_about_password_email_failure(user_id, raw_url, provider_error)

    db = SessionLocal()
    try:
        notes = (
            db.query(Notification)
            .filter(Notification.title == "Password reset email failed")
            .order_by(Notification.id.desc())
            .all()
        )
        assert len(notes) > before
        message = notes[0].message
    finally:
        db.close()

    assert raw_url not in message
    assert "raw-reset-token-should-not-persist" not in message
    assert "token=" not in message.lower()
    assert "provider details suppressed" in message


def test_cors_rejects_untrusted_credentialed_origin(client):
    r = client.options(
        "/api/auth/me",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in {400, 403}
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"


def test_sales_order_attachment_requires_valid_signature(client, auth_headers):
    r = client.post(
        "/api/sales-orders/printing-attachments/upload",
        files={"file": ("design.png", _PNG, "image/png")},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    signed = r.json()["file_url"]
    assert "sig=" in signed and "exp=" in signed

    # The signed URL serves the file (no auth header needed — that's the point).
    assert client.get(signed).status_code == 200

    bare = signed.split("?", 1)[0]
    # Unsigned access is refused.
    assert client.get(bare).status_code == 403
    # Tampered / forged signature is refused.
    assert client.get(bare + "?exp=9999999999&sig=deadbeef").status_code == 403


def test_sales_order_persists_bare_path_and_resigns_on_read(client, auth_headers):
    up = client.post(
        "/api/sales-orders/printing-attachments/upload",
        files={"file": ("art.png", _PNG, "image/png")},
        headers=auth_headers,
    ).json()

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "printing_attachments": [up],
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 5, "unit_price": 10.0}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    detail = client.get(f"/api/sales-orders/{sid}", headers=auth_headers).json()
    atts = detail["printing_attachments"]
    assert atts and "sig=" in atts[0]["file_url"]
    # Each read mints a fresh working link.
    assert client.get(atts[0]["file_url"]).status_code == 200

    # Status-change endpoints (confirm) also return signed, loadable URLs.
    confirmed = client.post(f"/api/sales-orders/{sid}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200, confirmed.text
    catts = confirmed.json()["printing_attachments"]
    assert catts and "sig=" in catts[0]["file_url"]
    assert client.get(catts[0]["file_url"]).status_code == 200


def test_printable_package_label_escapes_database_values(client, auth_headers):
    po = client.post(
        "/api/production-orders",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 10,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 10}],
        },
        headers=auth_headers,
    )
    assert po.status_code == 201, po.text
    payload = {
        "production_order_id": po.json()["id"],
        "model_id": 1,
        "color": "<script>alert(1)</script>",
        "package_type": "bag",
        "capacity": 60,
        "weight_kg": 12.345,
        "items": [
            {"model_id": 1, "color": "<script>alert(1)</script>", "size": "<img src=x onerror=alert(2)>", "quantity": 10},
        ],
    }
    r = client.post("/api/packages", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    pkg_id = r.json()["id"]

    label = client.get(f"/api/packages/{pkg_id}/label", headers=auth_headers)
    assert label.status_code == 200, label.text
    assert "<script>alert(1)</script>" not in label.text
    assert "<img src=x onerror=alert(2)>" not in label.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in label.text
    assert "&lt;img src=x onerror=alert(2)&gt;" in label.text
    assert "12.345 kg" in label.text


def test_model_file_storage_requires_authentication(client, auth_headers):
    up = client.post(
        "/api/models/1/images/upload",
        files={"file": ("model.png", _PNG, "image/png")},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    file_url = up.json()["file_url"]

    client.cookies.clear()
    assert client.get(file_url).status_code == 401
    assert client.get(file_url, headers=auth_headers).status_code == 200


def test_model_file_thumbnail_is_authenticated_and_cacheable(client, auth_headers):
    up = client.post(
        "/api/models/1/images/upload",
        files={"file": ("model-preview.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    file_url = up.json()["file_url"]
    thumb_url = file_url.replace("/storage/model-files/", "/storage/model-files/thumb/") + "?size=320"

    client.cookies.clear()
    assert client.get(thumb_url).status_code == 401

    thumb = client.get(thumb_url, headers=auth_headers)
    assert thumb.status_code == 200, thumb.text
    assert thumb.headers["content-type"].startswith("image/webp")
    assert "max-age" in thumb.headers["cache-control"]


def test_model_file_survives_missing_filesystem_copy(client, auth_headers):
    from app.core.config import settings

    up = client.post(
        "/api/models/1/images/upload",
        data={"image_type": "model"},
        files={"file": ("model-db.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert up.status_code == 201, up.text
    file_url = up.json()["file_url"]
    file_name = file_url.rsplit("/", 1)[-1]
    abs_path = os.path.join(settings.MODEL_FILES_DIR, file_name)
    assert os.path.exists(abs_path)

    model = client.get("/api/models/1", headers=auth_headers)
    assert model.status_code == 200, model.text
    uploaded = next(img for img in model.json()["images"] if img["file_url"] == file_url)
    assert uploaded["is_primary"] is True

    os.remove(abs_path)
    original = client.get(file_url, headers=auth_headers)
    assert original.status_code == 200, original.text
    assert original.content.startswith(b"\x89PNG")

    thumb_url = file_url.replace("/storage/model-files/", "/storage/model-files/thumb/") + "?size=320"
    thumb = client.get(thumb_url, headers=auth_headers)
    assert thumb.status_code == 200, thumb.text
    assert thumb.headers["content-type"].startswith("image/webp")

# ---------- Additional hardening regressions ----------

def test_browser_login_does_not_return_bearer_token(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "logged_in"}
    assert "access_token" not in r.text


def test_api_token_endpoint_returns_bearer_token_without_setting_cookie(client):
    r = client.post("/api/auth/token", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert "set-cookie" not in {k.lower(): v for k, v in r.headers.items()}


def test_untrusted_origin_cannot_make_cookie_authenticated_state_change(client):
    login = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert login.status_code == 200, login.text

    r = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_signed_storage_urls_use_file_signing_secret_not_jwt_secret(monkeypatch):
    from app.core import signing

    monkeypatch.setattr(signing.settings, "FILE_SIGNING_SECRET", "file-signing-secret-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(signing.settings, "JWT_SECRET", "jwt-secret-abcdefghijklmnopqrstuvwxyz")
    signed = signing.sign_path("/storage/sales-order-files/example.png", ttl_seconds=60)
    assert signed and "sig=" in signed
    bare, query = signed.split("?", 1)
    params = dict(part.split("=", 1) for part in query.split("&"))

    monkeypatch.setattr(signing.settings, "JWT_SECRET", "changed-jwt-secret-abcdefghijklmnopqrstuvwxyz")
    assert signing.verify_path(bare, params["exp"], params["sig"])

    monkeypatch.setattr(signing.settings, "FILE_SIGNING_SECRET", "changed-file-secret-abcdefghijklmnopqrstuvwxyz")
    assert not signing.verify_path(bare, params["exp"], params["sig"])


def test_upload_validation_helper_rejects_oversize_without_unbounded_read(client):
    import pytest
    from fastapi import HTTPException

    async def run_case():
        from app.core.uploads import read_validated_upload_content

        class FakeUpload:
            def __init__(self, body: bytes):
                self.body = body
                self.offset = 0
                self.read_sizes: list[int] = []

            async def read(self, size: int = -1):
                self.read_sizes.append(size)
                if size == -1:
                    size = len(self.body) - self.offset
                chunk = self.body[self.offset:self.offset + size]
                self.offset += len(chunk)
                return chunk

        upload = FakeUpload(_PNG + b"x" * 64)
        with pytest.raises(HTTPException) as exc:
            await read_validated_upload_content(upload, ".png", 16, chunk_size=8)
        assert exc.value.status_code == 400
        assert upload.read_sizes
        assert -1 not in upload.read_sizes
        assert max(upload.read_sizes) <= 8

    import asyncio
    asyncio.run(run_case())


def test_global_rate_limit_rejects_excess_requests(client, monkeypatch):
    from app.core.config import settings
    from app.core.shared_store import reset_shared_counter_store_for_tests

    reset_shared_counter_store_for_tests()
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "GLOBAL_RATE_LIMIT_WINDOW_SECONDS", 60)

    headers = {"x-forwarded-for": "203.0.113.10"}
    assert client.get("/api/auth/login-panel", headers=headers).status_code == 200
    assert client.get("/api/auth/login-panel", headers=headers).status_code == 200
    limited = client.get("/api/auth/login-panel", headers=headers)
    assert limited.status_code == 429
    assert limited.headers.get("retry-after")

    reset_shared_counter_store_for_tests()
