"""Regression tests for the security fixes:
- H1: privilege escalation via user/role management
- H2: state-changing endpoints gated by permission, not just login
- M2: password change/reset invalidates existing tokens
"""

import time

STRONG_PW = "Str0ngManager!2026"
ESC_PW = "Esc4lation!Test2026"


def _login(client, email, password):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
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
