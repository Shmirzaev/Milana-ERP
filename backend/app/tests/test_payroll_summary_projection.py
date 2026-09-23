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

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

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
