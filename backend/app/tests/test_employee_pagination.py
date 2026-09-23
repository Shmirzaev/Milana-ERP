from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.hr import list_employees
from app.db.session import SessionLocal
from app.models import Employee, User
from app.tests.test_task_assignment_authorization import _actor


def _seed_employees(factory_code: str, count: int) -> list[int]:
    suffix = uuid4().hex[:12]
    with SessionLocal() as db:
        rows = [
            Employee(
                factory_code=factory_code,
                employee_no=f"{number + 1}{suffix[:6]}",
                full_name=f"Paged employee {suffix} {number:04d}",
                position="Operator",
                phone=f"+99890{number:07d}",
                salary=number + 100,
                status="active",
                joined_at=datetime(2096, 1, 1, tzinfo=timezone.utc) + timedelta(days=number),
                hr_profile_json={"page_case": suffix},
            )
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return [int(row.id) for row in rows]


def _select_trace(db, callback):
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select"):
            statements.append(normalized)

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        return callback(), statements
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_employee_page_bounds_factory_rows_and_matches_private_legacy_prefix(row_count, monkeypatch):
    monkeypatch.setattr("app.api.routes.hr.settings.BACKFILL_EMPLOYEES_FROM_USERS", False)
    user_id, _ = _actor(permissions=("hr.employees",), factory="ECO")
    with SessionLocal() as db:
        baseline = db.query(Employee).filter(Employee.factory_code == "ECO").count()
    employee_ids = _seed_employees("ECO", row_count)
    _seed_employees("BST", 1)

    with SessionLocal() as db:
        current = db.get(User, user_id)
        _ = current.role
        legacy, legacy_statements = _select_trace(
            db,
            lambda: list_employees(db, current, limit=500),
        )
    with SessionLocal() as db:
        current = db.get(User, user_id)
        _ = current.role
        page, page_statements = _select_trace(
            db,
            lambda: list_employees(db, current, page=1, page_size=50),
        )

    expected_ids = list(reversed(employee_ids))[:50]
    assert [row["id"] for row in legacy[:50]] == expected_ids
    assert [row["id"] for row in page["rows"]] == expected_ids
    assert page["rows"] == legacy[:50]
    assert all(row["factory_code"] == "ECO" for row in page["rows"])
    assert all("phone" in row and "salary" in row and "hr_profile_json" in row for row in page["rows"])
    assert page["total"] == baseline + row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is ((baseline + row_count) > 50)
    assert len(page["rows"]) <= 50
    assert len(legacy_statements) == 1
    assert len(page_statements) == 2
    count_statement = next(statement for statement in page_statements if "count(" in statement)
    assert "count(employees.id)" in count_statement
    assert "employees.factory_code = ?" in count_statement
    assert " from (select employees." not in count_statement
    row_statement = next(statement for statement in page_statements if " order by employees.id desc" in statement)
    assert "employees.factory_code = ?" in row_statement
    assert " limit ? offset ?" in row_statement


def test_employee_page_http_contract_preserves_legacy_privacy_and_auth(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.hr.settings.BACKFILL_EMPLOYEES_FROM_USERS", False)
    _, private_headers = _actor(permissions=("hr.employees",), factory="ECO")
    private_id = _seed_employees("ECO", 1)[0]

    legacy = client.get("/api/employees?limit=1", headers=private_headers)
    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert legacy.json()[0]["id"] == private_id
    assert {"phone", "salary", "hr_profile_json"} <= set(legacy.json()[0])

    paged = client.get("/api/employees?page=1&page_size=1", headers=private_headers)
    assert paged.status_code == 200
    body = paged.json()
    assert body["rows"] == legacy.json()
    assert body["page"] == 1
    assert body["page_size"] == 1

    _, public_headers = _actor(factory="BST")
    public_id = _seed_employees("BST", 1)[0]
    public_page = client.get("/api/employees?page=1&page_size=1", headers=public_headers)
    assert public_page.status_code == 200
    assert public_page.json()["rows"][0]["id"] == public_id
    assert not ({"phone", "salary", "hr_profile_json"} & set(public_page.json()["rows"][0]))

    assert client.get("/api/employees?page_size=501", headers=private_headers).status_code == 422
    assert client.get("/api/employees?page=1&page_size=1").status_code == 401
