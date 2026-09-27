from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes import hr
from app.models import Employee
from app.tests.conftest import TestSessionLocal, test_engine


@pytest.mark.parametrize("include_private", [False, True])
def test_employee_detail_projects_fields_required_by_visibility(client, auth_headers, monkeypatch, include_private):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        employee = Employee(
            factory_code="MIL",
            employee_no=f"DETAIL-{marker}",
            full_name=f"Detail employee {marker}",
            position="Operator",
            phone="555-0199",
            salary=1234.50,
            status="active",
            hr_profile_json={"private_marker": marker},
        )
        db.add(employee)
        db.commit()
        employee_id = employee.id

    monkeypatch.setattr(hr, "_can_view_private_employee_fields", lambda _user: include_private)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/employees/{employee_id}", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == f"Detail employee {marker}"
    assert ("phone" in body) is include_private
    assert ("salary" in body) is include_private
    assert ("hr_profile_json" in body) is include_private
    employee_reads = [statement for statement in statements if " from employees " in statement]
    assert len(employee_reads) == 1, statements  # No deferred Employee-column loads.
    selected_columns = employee_reads[0].split(" from employees", 1)[0]
    for private_field in ("employees.phone", "employees.salary", "employees.hr_profile_json"):
        assert (private_field in selected_columns) is include_private
