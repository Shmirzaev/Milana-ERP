from sqlalchemy import event

from app.api.routes import hr
from app.models import Employee
from app.tests.conftest import TestSessionLocal, test_engine


def test_employee_list_has_bounded_default_and_explicit_limit(client, auth_headers):
    db = TestSessionLocal()
    try:
        rows = [
            Employee(factory_code="MIL", full_name=f"Bounded employee {idx}", status="active")
            for idx in range(501)
        ]
        db.add_all(rows)
        db.commit()
        newest_id = max(row.id for row in rows)
    finally:
        db.close()

    default = client.get("/api/employees", headers=auth_headers)
    assert default.status_code == 200, default.text
    assert len(default.json()) == 500
    assert default.json()[0]["id"] == newest_id

    explicit = client.get("/api/employees?limit=1", headers=auth_headers)
    assert explicit.status_code == 200, explicit.text
    assert len(explicit.json()) == 1
    assert explicit.json()[0]["id"] == newest_id

    rejected = client.get("/api/employees?limit=501", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text


def test_employee_list_omits_private_columns_when_caller_cannot_view_them(
    client, auth_headers, monkeypatch,
):
    with TestSessionLocal() as db:
        db.add(Employee(
            factory_code="MIL",
            full_name="Projection employee",
            status="active",
            phone="555-0100",
            salary=1234,
            hr_profile_json={"unused_payload": "x" * 10_000},
        ))
        db.commit()
    monkeypatch.setattr(hr, "_can_view_private_employee_fields", lambda _user: False)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = client.get("/api/employees?limit=1", headers=auth_headers)
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert "salary" not in response.json()[0]
    employee_reads = [statement for statement in statements if " from employees " in statement]
    assert len(employee_reads) == 1
    assert "employees.salary" not in employee_reads[0]
    assert "employees.hr_profile_json" not in employee_reads[0]
