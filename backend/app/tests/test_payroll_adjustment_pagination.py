from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.payroll import list_adjustments
from app.models import AuditLog, Employee, PayrollAdjustment
from app.schemas.payroll import PayrollAdjustmentOut
from app.tests.conftest import TestSessionLocal, test_engine


def _factory_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        factory_code="MIL",
        session_factory_code="MIL",
    )


def _seed_adjustments(count: int, *, factory_code: str = "MIL") -> tuple[int, list[int]]:
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        employee = Employee(
            factory_code=factory_code,
            employee_no=f"PERF35-{marker}",
            full_name=f"Bounded adjustment employee {marker}",
            status="active",
        )
        db.add(employee)
        db.flush()
        adjustments = [
            PayrollAdjustment(
                factory_code=factory_code,
                employee_id=employee.id,
                adjustment_type="bonus",
                amount=Decimal(index + 1),
                currency="UZS",
                reason=f"Pagination adjustment {marker}-{index}",
                created_at=datetime(2098, 1, 1, tzinfo=timezone.utc),
            )
            for index in range(count)
        ]
        db.add_all(adjustments)
        db.commit()
        return int(employee.id), [int(adjustment.id) for adjustment in adjustments]


def _read(employee_id: int, **kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_adjustments(db, _factory_user(), employee_id=employee_id, **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[PayrollAdjustment]) -> list[dict]:
    return [PayrollAdjustmentOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_adjustment_pages_bound_sql_and_preserve_legacy_payload(count):
    employee_id, created_ids = _seed_adjustments(count)

    page, statements = _read(employee_id, page=1, page_size=50)
    legacy, legacy_statements = _read(employee_id, page=None, page_size=None)
    expected_count = min(count, 50)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:expected_count]
    assert [row["id"] for row in page["rows"]] == [row.id for row in legacy[:expected_count]]
    assert all(row["employee_name"].startswith("Bounded adjustment employee ") for row in page["rows"])
    assert all(row["department_id"] is None and row["department_name"] is None for row in page["rows"])
    assert all("employee_name" not in row for row in _payload(legacy[:expected_count]))
    assert len(statements) == 3, statements
    assert " limit ? offset ?" in statements[1]
    assert "employees.id in" in statements[2]
    assert len(legacy_statements) == 1, legacy_statements


def test_adjustment_page_contract_factory_auth_filters_and_no_writes(client, auth_headers):
    employee_id, [adjustment_id] = _seed_adjustments(1)
    _seed_adjustments(1, factory_code="BST")
    with TestSessionLocal() as db:
        before = (db.query(PayrollAdjustment).count(), db.query(AuditLog).count())

    legacy = client.get(
        "/api/payroll/adjustments",
        params={"employee_id": employee_id},
        headers=auth_headers,
    )
    assert legacy.status_code == 200, legacy.text
    assert [row["id"] for row in legacy.json()] == [adjustment_id]

    response = client.get(
        "/api/payroll/adjustments",
        params={"employee_id": employee_id, "page": 1, "page_size": 1},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    response_body = response.json()
    assert response_body["rows"] == [{
        **legacy.json()[0],
        "employee_name": response_body["rows"][0]["employee_name"],
        "department_id": None,
        "department_name": None,
    }]
    assert response_body == {
        "rows": response_body["rows"],
        "total": 1,
        "page": 1,
        "page_size": 1,
        "has_more": False,
    }

    periods = client.get("/api/payroll/periods?page=1&page_size=1", headers=auth_headers)
    assert periods.status_code == 200, periods.text
    assert periods.json() == {"rows": [], "total": 0, "page": 1, "page_size": 1, "has_more": False}

    assert client.get(
        "/api/payroll/adjustments?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/payroll/adjustments?page=1&page_size=1").status_code == 401

    with TestSessionLocal() as db:
        after = (db.query(PayrollAdjustment).count(), db.query(AuditLog).count())
    assert after == before
