from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.payroll import list_records
from app.models import Department, Employee, PayrollRecord
from app.tests.conftest import TestSessionLocal, test_engine


def _factory_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        factory_code="MIL",
        session_factory_code="MIL",
    )


def _seed_records(count, *, status="recorded"):
    marker = uuid4().hex[:10]
    scanned_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    with TestSessionLocal() as db:
        department = db.query(Department).filter(Department.code == "HR").first()
        assert department is not None
        employees = [
            Employee(
                factory_code="MIL",
                employee_no=f"PERF35-{marker}-{index:04d}",
                full_name=f"Bounded payroll employee {index}",
                department_id=department.id,
                status="active",
            )
            for index in range(count)
        ]
        db.add_all(employees)
        db.flush()
        records = [
            PayrollRecord(
                factory_code="MIL",
                dedupe_key=f"{marker}{index:054d}",
                employee_id=employee.id,
                operation_name=f"Bounded operation {index}",
                quantity=Decimal("1"),
                rate_per_piece=Decimal("2"),
                total_amount=Decimal("2"),
                scanned_at=scanned_at,
                source="perf35_test",
                status=status,
            )
            for index, employee in enumerate(employees)
        ]
        db.add_all(records)
        db.commit()
        return [int(record.id) for record in records]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_records(db, _factory_user(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_payroll_record_pages_preserve_legacy_and_bound_supporting_reads(count):
    record_ids = _seed_records(count)
    returned_count = min(count, 50)

    page, statements = _read(status="recorded", page=1, page_size=50)
    legacy, _ = _read(status="recorded", limit=1000)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(record_ids))[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert len(statements) == 4, statements
    employee_reads = [statement for statement in statements if " from employees " in statement]
    department_reads = [statement for statement in statements if " from departments " in statement]
    assert len(employee_reads) == len(department_reads) == 1
    assert employee_reads[0].count("?") == returned_count
    assert department_reads[0].count("?") == 1


def test_payroll_record_page_filters_before_count(client, auth_headers):
    [record_id] = _seed_records(1, status="voided")

    response = client.get(
        "/api/payroll/records?status=voided&page=1&page_size=50",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == [record_id]
    assert {key: page[key] for key in ("page", "page_size", "has_more")} == {
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }


def test_payroll_record_page_size_is_bounded(client, auth_headers):
    response = client.get("/api/payroll/records?page_size=501", headers=auth_headers)
    assert response.status_code == 422, response.text
