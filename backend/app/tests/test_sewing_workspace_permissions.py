from datetime import date
from uuid import uuid4


PASSWORD = "SewingWorkspace!2026"


def _role_id(client, headers, name: str) -> int:
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200, response.text
    return int(next(row["id"] for row in response.json() if row["name"] == name))


def _department_id(client, headers, code: str) -> int:
    response = client.get("/api/departments", headers=headers)
    assert response.status_code == 200, response.text
    return int(next(row["id"] for row in response.json() if row["code"] == code))


def _create_user_headers(client, admin_headers, *, role: str, department: str) -> dict[str, str]:
    suffix = uuid4().hex[:8]
    email = f"{role.lower()}.workspace.{suffix}@example.com"
    response = client.post(
        "/api/users",
        json={
            "name": f"{role} Workspace Test",
            "email": email,
            "password": PASSWORD,
            "role_id": _role_id(client, admin_headers, role),
            "department_id": _department_id(client, admin_headers, department),
            "is_active": True,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/auth/token", data={"username": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_sewing_workspace_is_limited_to_sewing_role(client, auth_headers):
    sewing_headers = _create_user_headers(
        client,
        auth_headers,
        role="Sewing",
        department="SEW",
    )
    planning_headers = _create_user_headers(
        client,
        auth_headers,
        role="Planning",
        department="PLN",
    )

    sewing_me = client.get("/api/auth/me", headers=sewing_headers)
    planning_me = client.get("/api/auth/me", headers=planning_headers)
    assert sewing_me.status_code == 200, sewing_me.text
    assert planning_me.status_code == 200, planning_me.text
    assert "sewing.workspace" in sewing_me.json()["permissions"]
    assert "sewing.workspace" not in planning_me.json()["permissions"]

    # Keep this permission fixture isolated from daily aggregate tests that use today.
    report_date = date(2099, 12, 31).isoformat()
    assert client.get(
        f"/api/sewing-daily-reports?report_date={report_date}",
        headers=sewing_headers,
    ).status_code == 200
    assert client.get(
        f"/api/sewing-daily-reports?report_date={report_date}",
        headers=planning_headers,
    ).status_code == 403
    assert client.get(
        f"/api/sewing-daily-reports/export.xlsx?report_date={report_date}",
        headers=sewing_headers,
    ).status_code == 200
    assert client.get(
        f"/api/sewing-daily-reports/export.pdf?report_date={report_date}",
        headers=planning_headers,
    ).status_code == 403

    # Planning still needs the shared read-only list for production assignment screens.
    assert client.get("/api/sewing-flows", headers=planning_headers).status_code == 200

    code = f"SW-{uuid4().hex[:8].upper()}"
    allowed_create = client.post(
        "/api/sewing-flows",
        json={"name": f"Allowed {code}", "code": code, "capacity_per_day": 100, "is_active": True},
        headers=auth_headers,
    )
    assert allowed_create.status_code == 201, allowed_create.text
    flow_id = int(allowed_create.json()["id"])

    manual_payload = {
        "report_date": report_date,
        "sewing_flow_id": flow_id,
        "work_order_id": None,
        "manual_model_no": "MANUAL-ROLE-TEST",
        "sewn_qty": 5,
    }
    allowed_report = client.post("/api/sewing-daily-reports", json=manual_payload, headers=sewing_headers)
    assert allowed_report.status_code == 201, allowed_report.text
    denied_report = client.post("/api/sewing-daily-reports", json=manual_payload, headers=planning_headers)
    assert denied_report.status_code == 403, denied_report.text
