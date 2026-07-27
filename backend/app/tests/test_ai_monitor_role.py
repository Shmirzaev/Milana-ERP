from uuid import uuid4


def _login(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/token", data={"username": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_ai_monitor_role_can_report_but_not_administer(client, auth_headers):
    roles_response = client.get("/api/roles", headers=auth_headers)
    assert roles_response.status_code == 200, roles_response.text
    role = next(row for row in roles_response.json() if row["name"] == "AI Monitor")
    assert "*" not in role["permissions"]
    assert "admin.users" not in role["permissions"]
    assert "admin.audit" in role["permissions"]
    assert "management.view" in role["permissions"]

    password = "MonitorPass12345"
    email = f"ai.monitor.{uuid4().hex[:8]}@example.com"
    create_response = client.post(
        "/api/users",
        json={
            "name": "AI Monitor",
            "email": email,
            "password": password,
            "role_id": role["id"],
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 201, create_response.text
    monitor_headers = _login(client, email, password)

    audit_response = client.get("/api/audit-logs?include_total=true&page_size=5", headers=monitor_headers)
    assert audit_response.status_code == 200, audit_response.text

    management_response = client.get("/api/dashboard/management?tz=Asia/Tashkent", headers=monitor_headers)
    assert management_response.status_code == 200, management_response.text

    production_response = client.get("/api/dashboard/active-production", headers=monitor_headers)
    assert production_response.status_code == 200, production_response.text

    denied_user = client.post(
        "/api/users",
        json={
            "name": "Denied User",
            "email": f"denied.{uuid4().hex[:8]}@example.com",
            "password": "DeniedPass12345",
            "is_active": True,
        },
        headers=monitor_headers,
    )
    assert denied_user.status_code == 403

    denied_role = client.post(
        "/api/roles",
        json={"name": f"Denied {uuid4().hex[:8]}", "permissions": ["*"]},
        headers=monitor_headers,
    )
    assert denied_role.status_code == 403
