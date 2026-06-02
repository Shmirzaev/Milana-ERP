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


def test_forgot_password_notifies_admin_for_known_user(client, auth_headers):
    r = client.post("/api/auth/forgot-password", json={"email": "planning@example.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "If this account exists, an admin has been notified."

    r2 = client.get("/api/notifications?limit=20", headers=auth_headers)
    assert r2.status_code == 200
    assert any(
        n["title"] == "Password reset requested"
        and "planning@example.com" in (n.get("message") or "")
        and n.get("link") == "/admin/users"
        for n in r2.json()
    )


def test_forgot_password_uses_neutral_response_for_unknown_email(client):
    r = client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    assert r.status_code == 200
    assert r.json()["message"] == "If this account exists, an admin has been notified."


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
