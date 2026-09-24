from uuid import uuid4

from sqlalchemy import event

from app.api.routes.payroll import _load_employee_maps
from app.models import Department, Employee
from app.tests.conftest import TestSessionLocal
from app.tests.test_payroll import _create_user_with_permissions


def test_employee_context_maps_project_only_payroll_display_fields():
    suffix = uuid4().hex
    with TestSessionLocal() as db:
        department = Department(name=f"Payroll projection {suffix}", code=f"P-{suffix[:20]}")
        db.add(department)
        db.flush()
        employee = Employee(
            factory_code="MIL",
            full_name=f"Payroll Projection {suffix}",
            department_id=department.id,
            phone="private-phone",
            salary="1234.56",
            hr_profile_json={"private": "profile"},
        )
        db.add(employee)
        db.commit()
        employee_id = employee.id
        department_id = department.id

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            employees, departments = _load_employee_maps(db, {employee_id})
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)

    assert employees[employee_id].full_name == f"Payroll Projection {suffix}"
    assert employees[employee_id].department_id == department_id
    assert departments[department_id].name == f"Payroll projection {suffix}"
    employee_query = next(sql for sql in statements if "from employees" in sql)
    department_query = next(sql for sql in statements if "from departments" in sql)
    assert "employees.phone" not in employee_query
    assert "employees.salary" not in employee_query
    assert "employees.hr_profile_json" not in employee_query
    assert "departments.code" not in department_query


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
        legacy_sql = str(
            db.query(Employee, Department)
            .outerjoin(Department, Employee.department_id == Department.id)
            .statement.compile(dialect=db.bind.dialect)
        ).lower()
        bind = db.get_bind()
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(bind, "before_cursor_execute", capture)
    try:
        result = client.get("/api/payroll/employees/search", params={"q": suffix}, headers=auth_headers).json()
    finally:
        event.remove(bind, "before_cursor_execute", capture)

    assert len(result["items"]) == 20
    assert result["has_more"] is True
    assert [item["employee_name"] for item in result["items"]] == [f"Search {suffix} {index:02d}" for index in range(20)]
    employee_read = next(statement for statement in statements if " from employees " in statement)
    assert all(f"employees.{column}" in employee_read for column in (
        "id", "employee_no", "user_id", "full_name", "department_id", "position", "status",
    ))
    assert "employees.salary" not in employee_read
    assert "employees.hr_profile_json" not in employee_read
    assert "departments.name" in employee_read
    assert "departments.code" in employee_read
    assert "employees.salary" in legacy_sql
    assert "employees.hr_profile_json" in legacy_sql
    for query in [f"{suffix}%", f"{suffix}_", "  "]:
        result = client.get("/api/payroll/employees/search", params={"q": query}, headers=auth_headers)
        assert result.status_code == 200
        assert result.json() == {"items": [], "has_more": False}
    for query in ["a", "x" * 101]:
        assert client.get("/api/payroll/employees/search", params={"q": query}, headers=auth_headers).status_code == 422


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
