from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.payroll import payroll_summary
from app.models import (
    Department,
    Employee,
    PayrollAdjustment,
    PayrollPeriod,
    PayrollRecord,
)
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_payroll import _create_user_with_permissions


def _seed_summary_rows(count):
    marker = uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    with TestSessionLocal() as db:
        department = db.query(Department).filter(Department.code == "HR").one()
        period = PayrollPeriod(
            factory_code="ECO",
            period_no=f"PERF35-{marker}",
            name=f"Projection {marker}",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
            status="open",
        )
        db.add(period)
        db.flush()
        employees = [
            Employee(
                factory_code="ECO",
                employee_no=f"PERF35-{marker}-{index:04d}",
                full_name=f"Summary employee {index}",
                department_id=department.id,
                status="active",
            )
            for index in range(count)
        ]
        db.add_all(employees)
        db.flush()
        records = [
            PayrollRecord(
                factory_code="ECO",
                payroll_period_id=period.id,
                dedupe_key=f"{marker}{index:054d}",
                employee_id=employee.id,
                operation_section="sewing",
                operation_code="SEW-01",
                operation_name="Assembly",
                quantity=Decimal("2"),
                rate_per_piece=Decimal("2.5"),
                total_amount=Decimal("5"),
                currency="UZS",
                scanned_at=now,
                source="perf35_summary_test",
                status="recorded",
                raw_employee_json={"unused": "employee data" * 50},
                raw_work_json={"unused": "work data" * 50},
                notes="unused payroll note",
            )
            for index, employee in enumerate(employees)
        ]
        adjustments = [
            PayrollAdjustment(
                factory_code="ECO",
                payroll_period_id=period.id,
                employee_id=employee.id,
                adjustment_type="bonus",
                amount=Decimal("1"),
                reason="summary projection test",
            )
            for employee in employees
        ]
        db.add_all([*records, *adjustments])
        db.commit()
        return int(period.id)


@pytest.mark.parametrize("count", [1, 50, 401])
def test_payroll_summary_projects_aggregate_fields_only(count):
    period_id = _seed_summary_rows(count)
    current = SimpleNamespace(factory_code="ECO", session_factory_code="ECO")
    with TestSessionLocal() as db:
        legacy_record_sql = str(
            db.query(PayrollRecord)
            .filter(PayrollRecord.payroll_period_id == period_id)
            .statement.compile(dialect=test_engine.dialect)
        ).lower()
        legacy_adjustment_sql = str(
            db.query(PayrollAdjustment)
            .filter(PayrollAdjustment.payroll_period_id == period_id)
            .statement.compile(dialect=test_engine.dialect)
        ).lower()
        statements = []
        execution_options = []

        def capture(_connection, _cursor, statement, _parameters, context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))
                execution_options.append(dict(context.execution_options))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            result = payroll_summary(db, current, period_id=period_id)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)

    record_reads = [statement for statement in statements if " from payroll_records " in statement]
    adjustment_reads = [statement for statement in statements if " from payroll_adjustments " in statement]
    assert len(record_reads) == len(adjustment_reads) == 1
    assert "raw_work_json" not in record_reads[0]
    assert "raw_employee_json" not in record_reads[0]
    assert "payroll_records.notes" not in record_reads[0]
    assert "source_payroll_record_id" not in adjustment_reads[0]
    assert "reason" not in adjustment_reads[0]
    streamed_reads = [
        options
        for statement, options in zip(statements, execution_options, strict=True)
        if " from payroll_records " in statement
        or " from payroll_adjustments " in statement
    ]
    assert len(streamed_reads) == 2
    assert all(options.get("yield_per") == 400 for options in streamed_reads)
    assert all(options.get("stream_results") is True for options in streamed_reads)
    assert "raw_work_json" in legacy_record_sql
    assert "raw_employee_json" in legacy_record_sql
    assert "payroll_records.notes" in legacy_record_sql
    assert "source_payroll_record_id" in legacy_adjustment_sql
    assert "payroll_adjustments.reason" in legacy_adjustment_sql
    assert result.records_count == count
    assert result.adjustment_count == count
    assert result.quantity == Decimal(2 * count)
    assert result.piecework_amount == Decimal(5 * count)
    assert result.bonus_amount == Decimal(count)
    assert result.total_amount == Decimal(6 * count)


@pytest.mark.parametrize("count", [1, 50, 401])
def test_payroll_summary_pages_employee_and_operation_groups_with_global_totals(count):
    period_id = _seed_summary_rows(count)
    current = SimpleNamespace(factory_code="ECO", session_factory_code="ECO")
    with TestSessionLocal() as db:
        first = payroll_summary(db, current, period_id=period_id, page=1, page_size=50)
        second = payroll_summary(db, current, period_id=period_id, page=2, page_size=50)

    assert first.records_count == count
    assert first.adjustment_count == count
    assert first.total_amount == Decimal(6 * count)
    assert first.employees_total == count
    assert first.employee_page == 1
    assert first.employee_page_size == 50
    assert first.employees_has_more is (count > 50)
    assert len(first.employees) == min(count, 50)
    assert all(len(employee.operations) == 1 for employee in first.employees)
    if count > 50:
        assert second.employee_page == 2
        assert second.employees_total == count
        assert len(second.employees) == min(count - 50, 50)
        assert not ({row.employee_id for row in first.employees} & {row.employee_id for row in second.employees})
        assert all(len(employee.operations) == 1 for employee in second.employees)


def test_payroll_summary_search_filters_groups_but_keeps_global_totals():
    period_id = _seed_summary_rows(50)
    current = SimpleNamespace(factory_code="ECO", session_factory_code="ECO")
    with TestSessionLocal() as db:
        result = payroll_summary(
            db,
            current,
            period_id=period_id,
            employee_search="summary employee 49",
            page_size=1,
        )

    assert result.records_count == 50
    assert result.total_amount == Decimal(300)
    assert result.employees_total == 1
    assert result.employees_has_more is False
    assert [row.employee_name for row in result.employees] == ["Summary employee 49"]


def test_payroll_summary_page_scopes_operation_query_to_returned_employees():
    period_id = _seed_summary_rows(401)
    current = SimpleNamespace(factory_code="ECO", session_factory_code="ECO")
    with TestSessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            result = payroll_summary(db, current, period_id=period_id, page=1, page_size=50)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)

    record_reads = [statement for statement in statements if " from payroll_records " in statement]
    assert len(record_reads) == 2
    assert "payroll_records.employee_id =" in record_reads[1]
    assert "coalesce(payroll_records.currency" in record_reads[1]
    assert len(result.employees) == 50
    assert result.employees_total == 401


def test_payroll_summary_currency_split_pages_keep_operation_groups_attached():
    marker = uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    current = SimpleNamespace(factory_code="ECO", session_factory_code="ECO")
    with TestSessionLocal() as db:
        department = db.query(Department).filter(Department.code == "HR").one()
        employee = Employee(
            factory_code="ECO",
            employee_no=f"PERF35-CURRENCY-{marker}",
            full_name=f"Currency employee {marker}",
            department_id=department.id,
            status="active",
        )
        period = PayrollPeriod(
            factory_code="ECO",
            period_no=f"PERF35-CURRENCY-{marker}",
            name=f"Currency projection {marker}",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
            status="open",
        )
        db.add_all([employee, period])
        db.flush()
        db.add_all([
            PayrollRecord(
                factory_code="ECO",
                payroll_period_id=period.id,
                dedupe_key=f"{marker}{index:054d}",
                employee_id=employee.id,
                operation_section="sewing",
                operation_code=f"SEW-{index}",
                operation_name=f"Assembly {index}",
                quantity=Decimal("2"),
                rate_per_piece=Decimal("2.5"),
                total_amount=Decimal("5"),
                currency=currency,
                scanned_at=now,
                source="perf35_summary_currency_test",
                status="recorded",
            )
            for index, currency in enumerate(("USD", "UZS"))
        ])
        db.commit()
        period_id = int(period.id)

    with TestSessionLocal() as db:
        first = payroll_summary(db, current, period_id=period_id, page=1, page_size=1)
    with TestSessionLocal() as db:
        second = payroll_summary(db, current, period_id=period_id, page=2, page_size=1)

    assert first.employees_total == second.employees_total == 2
    assert len(first.employees) == len(second.employees) == 1
    for page in (first, second):
        employee_row = page.employees[0]
        assert len(employee_row.operations) == 1
        assert employee_row.operations[0].currency == employee_row.currency


def test_payroll_summary_paged_api_keeps_payroll_authorization(client, auth_headers):
    marker = uuid4().hex[:10]
    period_id = _seed_summary_rows(1)
    viewer = _create_user_with_permissions(
        client,
        auth_headers,
        email=f"summary-page-{marker}@example.com",
        factory_code="ECO",
        permissions=["payroll.view"],
    )

    response = client.get(
        f"/api/payroll/summary?period_id={period_id}&page=1&page_size=50&employee_search=Summary",
        headers=viewer,
    )
    assert response.status_code == 200, response.text
    assert response.json()["employees_total"] == 1
    assert client.get(
        f"/api/payroll/summary?period_id={period_id}&page=1&page_size=50"
    ).status_code == 401
