from app.core.security import LEGACY_DEFAULT_ADMIN_PASSWORD


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_admin_login(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body


def test_legacy_default_admin_login_is_blocked(client):
    r = client.post(
        "/api/auth/login",
        data={"username": "admin@example.com", "password": LEGACY_DEFAULT_ADMIN_PASSWORD},
    )
    assert r.status_code == 401


def test_me(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "admin@example.com"
    assert "*" in body["permissions"]


def test_login_bad_password(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401


def test_forgot_password_sends_reset_link_for_known_user(client, auth_headers, monkeypatch):
    sent = {}

    def fake_send(to_email, display_name, reset_url):
        sent["to_email"] = to_email
        sent["display_name"] = display_name
        sent["reset_url"] = reset_url
        return True

    monkeypatch.setattr("app.api.routes.auth.secrets.token_urlsafe", lambda _: "known-reset-token")
    monkeypatch.setattr("app.api.routes.auth.send_password_reset_email", fake_send)

    r = client.post("/api/auth/forgot-password", json={"email": "planning@example.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "If this account exists, a reset link has been sent."
    assert sent["to_email"] == "planning@example.com"
    assert sent["reset_url"].endswith("/reset-password?token=known-reset-token")

    r2 = client.get("/api/notifications?limit=20", headers=auth_headers)
    assert r2.status_code == 200
    assert any(
        n["title"] == "Password reset requested"
        and "planning@example.com" in (n.get("message") or "")
        and "reset email was queued" in (n.get("message") or "")
        and n.get("link") == "/admin/users"
        for n in r2.json()
    )


def test_forgot_password_uses_neutral_response_for_unknown_email(client):
    r = client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "If this account exists, a reset link has been sent."


def test_forgot_password_notifies_admin_with_link_when_email_fails(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.api.routes.auth.secrets.token_urlsafe", lambda _: "failed-email-token")

    def fail_send(*args, **kwargs):
        raise RuntimeError("smtp blocked")

    monkeypatch.setattr("app.api.routes.auth.send_password_reset_email", fail_send)

    r = client.post("/api/auth/forgot-password", json={"email": "planning@example.com"})
    assert r.status_code == 200

    r2 = client.get("/api/notifications?limit=20", headers=auth_headers)
    assert r2.status_code == 200
    assert any(
        n["title"] == "Password reset email failed"
        and "failed-email-token" in (n.get("message") or "")
        and n.get("link", "").endswith("/reset-password?token=failed-email-token")
        for n in r2.json()
    )


def test_reset_password_accepts_valid_token(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.auth.secrets.token_urlsafe", lambda _: "reset-login-token")
    monkeypatch.setattr("app.api.routes.auth.send_password_reset_email", lambda *args, **kwargs: True)

    r = client.post("/api/auth/forgot-password", json={"email": "planning@example.com"})
    assert r.status_code == 200

    new_password = "PlanningResetPassword123!"
    r2 = client.post(
        "/api/auth/reset-password",
        json={
            "token": "reset-login-token",
            "new_password": new_password,
            "confirm_new_password": new_password,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["message"] == "password_reset"

    login = client.post("/api/auth/login", data={"username": "planning@example.com", "password": new_password})
    assert login.status_code == 200

    reused = client.post(
        "/api/auth/reset-password",
        json={
            "token": "reset-login-token",
            "new_password": "AnotherResetPassword123!",
            "confirm_new_password": "AnotherResetPassword123!",
        },
    )
    assert reused.status_code == 400


def test_login_rate_limit_after_repeated_failures(client):
    for _ in range(5):
        r = client.post("/api/auth/login", data={"username": "missing@example.com", "password": "wrong"})
        assert r.status_code == 401

    r = client.post("/api/auth/login", data={"username": "missing@example.com", "password": "wrong"})
    assert r.status_code == 429


def test_admin_user_password_requires_strength(client, auth_headers):
    r = client.post(
        "/api/users",
        json={"name": "Weak User", "email": "weak@example.com", "password": "demo12345"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "shared default" in r.text
