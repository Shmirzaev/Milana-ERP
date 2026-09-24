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
    assert len(page_statements) == 4
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


def test_employee_page_search_summaries_and_manager_name_are_exact_and_factory_scoped(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.hr.settings.BACKFILL_EMPLOYEES_FROM_USERS", False)
    _, eco_headers = _actor(permissions=("hr.employees",), factory="ECO")
    _, bst_headers = _actor(permissions=("hr.employees",), factory="BST")
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        manager = Employee(factory_code="ECO", full_name=f"Manager {suffix}", status="active", hr_profile_json={})
        outside_manager = Employee(factory_code="BST", full_name=f"Outside manager {suffix}", status="active", hr_profile_json={})
        db.add_all([manager, outside_manager])
        db.flush()
        rows = [
            Employee(
                factory_code="ECO", full_name=f"Searchable {suffix} {index:02d}",
                employee_no=f"{index + 1}{suffix[:5]}", position="Stitcher",
                manager_employee_id=manager.id if index == 0 else outside_manager.id if index == 1 else None,
                status="active" if index < 40 else "on_leave",
                hr_profile_json={f"key_{key}": "value" for key in range(5 if index < 2 else 1)},
            )
            for index in range(61)
        ]
        db.add_all(rows)
        db.commit()

    search = f"Searchable {suffix}"
    first = client.get("/api/employees", params={"page": 1, "page_size": 50, "search": search}, headers=eco_headers)
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == 61
    assert body["active_total"] == 40
    assert body["inactive_total"] == 21
    assert body["profile_coverage_percent"] == 3
    assert len(body["rows"]) == 50 and body["has_more"]
    second = client.get("/api/employees", params={"page": 2, "page_size": 50, "search": search}, headers=eco_headers).json()
    assert second["total"] == 61 and len(second["rows"]) == 11 and not second["has_more"]
    assert next(row for row in second["rows"] if row["full_name"].endswith("00"))["manager_name"] == f"Manager {suffix}"
    assert next(row for row in second["rows"] if row["full_name"].endswith("01")).get("manager_name") is None

    managers = client.get("/api/employees/manager-options", params={"search": suffix}, headers=eco_headers)
    assert managers.status_code == 200
    assert len(managers.json()["rows"]) <= 50
    assert all("Outside manager" not in row["full_name"] for row in managers.json()["rows"])

    option_suffix = uuid4().hex[:8]
    option_ids = _seed_employees("ECO", 52)
    with SessionLocal() as db:
        option_rows = db.query(Employee).filter(Employee.id.in_(option_ids)).all()
        for index, option in enumerate(option_rows):
            option.full_name = f"Option {option_suffix} {index:02d}"
        db.commit()
    options = client.get(
        "/api/employees/manager-options",
        params={"search": f"Option {option_suffix}", "selected_id": option_ids[-1]},
        headers=eco_headers,
    )
    assert options.status_code == 200
    assert len(options.json()["rows"]) == 50 and options.json()["has_more"]
    assert option_ids[-1] in {row["id"] for row in options.json()["rows"]}


def test_employee_search_escapes_like_wildcards_and_private_profile_summary(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.hr.settings.BACKFILL_EMPLOYEES_FROM_USERS", False)
    _, private_headers = _actor(permissions=("hr.employees",), factory="ECO")
    _, public_headers = _actor(factory="ECO")
    suffix = uuid4().hex[:8]
    with SessionLocal() as db:
        db.add_all([
            Employee(factory_code="ECO", full_name=f"Literal % {suffix}", status="active", hr_profile_json={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}),
            Employee(factory_code="ECO", full_name=f"Literal X {suffix}", status="active", hr_profile_json={}),
        ])
        db.commit()
    private = client.get("/api/employees", params={"page": 1, "page_size": 50, "search": f"% {suffix}"}, headers=private_headers)
    assert private.status_code == 200
    assert private.json()["total"] == 1
    assert private.json()["profile_coverage_percent"] == 100
    public = client.get("/api/employees", params={"page": 1, "page_size": 50, "search": f"% {suffix}"}, headers=public_headers)
    assert public.status_code == 200
    assert public.json()["profile_coverage_percent"] is None
    assert not ("hr_profile_json" in public.json()["rows"][0])
