from uuid import uuid4

from app.models import Employee
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions


def test_employee_search_is_scoped_minimal_and_permission_protected(client, auth_headers):
    suffix = uuid4().hex[:8]
    scanner = _create_user_with_permissions(
        client, auth_headers, email=f"search-{suffix}@example.com", permissions=["payroll.scan"],
    )
    viewer = _create_user_with_permissions(
        client, auth_headers, email=f"view-{suffix}@example.com", permissions=["payroll.view"],
    )
    with TestSessionLocal() as db:
        rows = [
            Employee(factory_code="MIL", full_name=f"Durdona Azamova {suffix}", employee_no=f"FIND-{suffix}", status="active"),
            Employee(factory_code="ECO", full_name=f"Durdona Azamova {suffix}", employee_no=f"ECO-{suffix}", status="active"),
            Employee(factory_code="MIL", full_name=f"Durdona Former {suffix}", status="inactive"),
        ]
        db.add_all(rows)
        db.commit()
        expected = rows[0].id
    for query in [f"{suffix} durdona", f"find-{suffix}"]:
        result = client.get("/api/payroll/employees/search", params={"q": query}, headers=scanner)
        assert result.status_code == 200, result.text
        assert [item["employee_id"] for item in result.json()["items"]] == [expected]
        item = result.json()["items"][0]
        assert item["type"] == "employee_payroll"
        assert item["employee_no"] == f"FIND-{suffix}"
        assert "salary" not in item and "phone" not in item and "passport" not in item
        assert result.json()["has_more"] is False
    assert client.get("/api/payroll/employees/search?q=Durdona", headers=viewer).status_code == 403
    assert client.get("/api/payroll/employees/search?q=Durdona").status_code == 401


def test_employee_search_bounds_and_literal_wildcards(client, auth_headers):
    suffix = uuid4().hex[:8]
    with TestSessionLocal() as db:
        db.add_all([
            Employee(factory_code="MIL", full_name=f"Search {suffix} {index:02d}", status="active")
            for index in range(23)
        ])
        db.commit()
    result = client.get("/api/payroll/employees/search", params={"q": suffix}, headers=auth_headers).json()
    assert len(result["items"]) == 20
    assert result["has_more"] is True
    assert [item["employee_name"] for item in result["items"]] == [f"Search {suffix} {index:02d}" for index in range(20)]
    for query in [f"{suffix}%", f"{suffix}_", "  "]:
        result = client.get("/api/payroll/employees/search", params={"q": query}, headers=auth_headers)
        assert result.status_code == 200
        assert result.json() == {"items": [], "has_more": False}
    for query in ["a", "x" * 101]:
        assert client.get("/api/payroll/employees/search", params={"q": query}, headers=auth_headers).status_code == 422
