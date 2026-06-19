from datetime import datetime, timedelta, timezone

from app.services.email import EmailDeliveryError


def _login(client, email, password):
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _role_id(client, auth_headers, name):
    r = client.get("/api/roles", headers=auth_headers)
    assert r.status_code == 200, r.text
    return next(role["id"] for role in r.json() if role["name"] == name)


def _dept_id(client, auth_headers, code):
    r = client.get("/api/departments", headers=auth_headers)
    assert r.status_code == 200, r.text
    return next(dept["id"] for dept in r.json() if dept["code"] == code)


def test_user_extra_permissions_are_effective(client, auth_headers):
    hr_role_id = _role_id(client, auth_headers, "HR")
    hr_dept_id = _dept_id(client, auth_headers, "HR")
    password = "ExtraAccess!2026"

    r = client.post(
        "/api/users",
        json={
            "name": "Finance Helper",
            "email": "finance.helper@example.com",
            "password": password,
            "role_id": hr_role_id,
            "department_id": hr_dept_id,
            "extra_permissions": ["finance.view"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["extra_permissions"] == ["finance.view"]

    helper_headers = _login(client, "finance.helper@example.com", password)
    me = client.get("/api/auth/me", headers=helper_headers)
    assert me.status_code == 200, me.text
    assert "hr.employees" in me.json()["permissions"]
    assert "finance.view" in me.json()["permissions"]

    finance = client.get("/api/finance/dashboard", headers=helper_headers)
    assert finance.status_code == 200, finance.text


def test_create_user_without_password_emails_setup_link(client, auth_headers, monkeypatch):
    sent = {}

    def fake_send(to_email, display_name, setup_url):
        sent["to_email"] = to_email
        sent["display_name"] = display_name
        sent["setup_url"] = setup_url
        return True

    monkeypatch.setattr("app.services.password_reset.secrets.token_urlsafe", lambda _: "new-user-setup-token")
    monkeypatch.setattr("app.services.password_reset.send_password_setup_email", fake_send)

    r = client.post(
        "/api/users",
        json={
            "name": "Setup Link User",
            "email": "setup.link.user@example.com",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["password_setup_email_sent"] is True
    assert r.json()["password_setup_email_error"] is None
    assert sent["to_email"] == "setup.link.user@example.com"
    assert sent["display_name"] == "Setup Link User"
    assert sent["setup_url"].endswith("/reset-password?token=new-user-setup-token")

    login = client.post(
        "/api/auth/token",
        data={"username": "setup.link.user@example.com", "password": "UnknownBeforeSetup!2026"},
    )
    assert login.status_code == 401

    new_password = "SetupLinkUser!2026"
    reset = client.post(
        "/api/auth/reset-password",
        json={
            "token": "new-user-setup-token",
            "new_password": new_password,
            "confirm_new_password": new_password,
        },
    )
    assert reset.status_code == 200, reset.text

    setup_headers = _login(client, "setup.link.user@example.com", new_password)
    me = client.get("/api/auth/me", headers=setup_headers)
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "setup.link.user@example.com"


def test_create_user_reports_setup_email_failure(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.password_reset.send_password_setup_email", lambda *args, **kwargs: False)

    r = client.post(
        "/api/users",
        json={
            "name": "No Mail Setup User",
            "email": "no.mail.setup@example.com",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["password_setup_email_sent"] is False
    assert "Email delivery is not configured" in body["password_setup_email_error"]


def test_create_user_reports_safe_provider_email_error(client, auth_headers, monkeypatch):
    def fail_send(*args, **kwargs):
        raise EmailDeliveryError(
            "raw provider response might include submitted content",
            "Email delivery failed: SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD/app password.",
        )

    monkeypatch.setattr("app.services.password_reset.send_password_setup_email", fail_send)

    r = client.post(
        "/api/users",
        json={
            "name": "Bad SMTP Setup User",
            "email": "bad.smtp.setup@example.com",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["password_setup_email_sent"] is False
    assert "SMTP authentication failed" in body["password_setup_email_error"]
    assert "raw provider response" not in body["password_setup_email_error"]


def test_password_setup_email_status_reports_hf_smtp_unavailable(client, auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv("SPACE_ID", "Shmirzaev/milana-erp-api")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "smtp@example.com")

    r = client.get("/api/users/password-setup-email-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert "Hugging Face" in body["message"]
    assert "RESEND_API_KEY" in body["message"]


def test_password_setup_email_status_reports_resend_available(client, auth_headers, monkeypatch):
    from app.core.config import settings

    monkeypatch.setenv("SPACE_ID", "Shmirzaev/milana-erp-api")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-resend-key")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "smtp@example.com")

    r = client.get("/api/users/password-setup-email-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"available": True, "message": None}


def test_admin_can_resend_password_setup_link(client, auth_headers, monkeypatch):
    sent = {}

    def fake_send(to_email, display_name, setup_url):
        sent["to_email"] = to_email
        sent["display_name"] = display_name
        sent["setup_url"] = setup_url
        return True

    r = client.post(
        "/api/users",
        json={
            "name": "Resend Setup User",
            "email": "resend.setup.user@example.com",
            "password": "ResendSetup!2026",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    monkeypatch.setattr("app.services.password_reset.secrets.token_urlsafe", lambda _: "resend-setup-token")
    monkeypatch.setattr("app.services.password_reset.send_password_setup_email", fake_send)

    resend = client.post(f"/api/users/{user_id}/password-setup", headers=auth_headers)
    assert resend.status_code == 200, resend.text
    assert resend.json()["password_setup_email_sent"] is True
    assert sent["to_email"] == "resend.setup.user@example.com"
    assert sent["display_name"] == "Resend Setup User"
    assert sent["setup_url"].endswith("/reset-password?token=resend-setup-token")


def test_limited_user_manager_cannot_grant_extra_permissions_they_lack(client, auth_headers):
    hr_dept_id = _dept_id(client, auth_headers, "HR")
    manager_password = "LimitedManager!2026"
    target_password = "TargetUser!2026"

    r = client.post(
        "/api/roles",
        json={"name": "LimitedExtraManager", "permissions": ["admin.users"]},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    manager_role_id = r.json()["id"]

    r = client.post(
        "/api/users",
        json={
            "name": "Limited Extra Manager",
            "email": "limited.extra.manager@example.com",
            "password": manager_password,
            "role_id": manager_role_id,
            "department_id": hr_dept_id,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    manager_headers = _login(client, "limited.extra.manager@example.com", manager_password)
    r = client.post(
        "/api/users",
        json={
            "name": "Extra Target",
            "email": "extra.target@example.com",
            "password": target_password,
            "department_id": hr_dept_id,
            "extra_permissions": ["finance.view"],
        },
        headers=manager_headers,
    )
    assert r.status_code == 403, r.text


def test_delete_user_detaches_existing_references(client, auth_headers):
    from app.db.session import SessionLocal
    from app.models import AuditLog, Employee, Notification, PasswordResetToken, User

    r = client.post(
        "/api/users",
        json={
            "name": "Delete Candidate",
            "email": "delete.candidate@example.com",
            "password": "DeleteCandidate!2026",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    db = SessionLocal()
    try:
        employee = Employee(user_id=user_id, full_name="Delete Candidate")
        audit = AuditLog(user_id=user_id, action="login", entity_type="User", entity_id=user_id)
        notification = Notification(user_id=user_id, title="Owned notification", message="delete me")
        reset_token = PasswordResetToken(
            user_id=user_id,
            token_hash="delete-candidate-token-hash",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([employee, audit, notification, reset_token])
        db.commit()
        employee_id = employee.id
        audit_id = audit.id
    finally:
        db.close()

    r = client.delete(f"/api/users/{user_id}", headers=auth_headers)
    assert r.status_code == 204, r.text

    db = SessionLocal()
    try:
        assert db.get(User, user_id) is None
        assert db.get(Employee, employee_id).user_id is None
        assert db.get(AuditLog, audit_id).user_id is None
        assert db.query(Notification).filter(Notification.user_id == user_id).count() == 0
        assert db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id).count() == 0
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "delete",
                AuditLog.entity_type == "User",
                AuditLog.entity_id == user_id,
            )
            .count()
            == 1
        )
    finally:
        db.close()
