def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_admin_login(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "admin12345"})
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body


def test_me(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "admin@example.com"
    assert "*" in body["permissions"]


def test_login_bad_password(client):
    r = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "wrong"})
    assert r.status_code == 401
