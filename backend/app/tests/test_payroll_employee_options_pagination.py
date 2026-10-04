from uuid import uuid4
from app.models import Employee
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions

def test_payroll_employee_options_page_inactive_selection_scope_and_projection(client, auth_headers):
    suffix = uuid4().hex[:8]
    viewer = _create_user_with_permissions(
        client, auth_headers, email=f"options-{suffix}@example.com", permissions=["payroll.view"],
    )
    with TestSessionLocal() as db:
        rows = [
            Employee(
                factory_code="MIL",
                full_name=f"Options {suffix} {index:03d}",
                employee_no=f"OPTIONS-{suffix}-{index:03d}",
                status="inactive" if index in (0, 54) else "active",
                salary="9876.50",
                hr_profile_json={"private": "not projected"},
            )
            for index in range(501)
        ]
        outsider = Employee(factory_code="ECO", full_name=f"Options {suffix} outsider", status="active")
        db.add_all([*rows, outsider])
        db.commit()
        selected_id = rows[0].id
        outsider_id = outsider.id

    first = client.get(
        "/api/payroll/employees/options",
        params={"search": suffix, "page": 1, "page_size": 50, "selected_id": selected_id},
        headers=viewer,
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 50
    assert first_body["has_more"] is True
    assert first_body["search"] == suffix
    assert first_body["selected"]["id"] == selected_id
    assert all("salary" not in row and "hr_profile_json" not in row for row in first_body["items"])

    second = client.get(
        "/api/payroll/employees/options",
        params={"search": suffix, "page": 2, "page_size": 50},
        headers=viewer,
    )
    assert second.status_code == 200, second.text
    assert [row["id"] for row in second.json()["items"]] == [row.id for row in rows[50:100]]
    assert second.json()["has_more"] is True

    legacy = client.get("/api/employees?limit=500", headers=viewer)
    assert legacy.status_code == 200, legacy.text
    assert selected_id not in {row["id"] for row in legacy.json()}
    selected_on_later_page = client.get(
        "/api/payroll/employees/options",
        params={"search": suffix, "page": 11, "page_size": 50, "selected_id": selected_id},
        headers=viewer,
    )
    assert selected_on_later_page.status_code == 200
    assert len(selected_on_later_page.json()["items"]) == 1
    assert selected_on_later_page.json()["has_more"] is False
    assert selected_on_later_page.json()["selected"]["id"] == selected_id

    cross_factory_selected = client.get(
        "/api/payroll/employees/options",
        params={"selected_id": outsider_id},
        headers=viewer,
    )
    assert cross_factory_selected.status_code == 200
    assert cross_factory_selected.json()["selected"] is None
    assert all(row["id"] != outsider_id for row in cross_factory_selected.json()["items"])
    assert client.get("/api/payroll/employees/options", headers=auth_headers).status_code == 200
    assert client.get("/api/payroll/employees/options").status_code == 401
    assert client.get("/api/payroll/employees/options?page_size=51", headers=viewer).status_code == 422


