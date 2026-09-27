from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.hr_workspace import dashboard
from app.db.session import SessionLocal
from app.models import (
    Department,
    Employee,
    HrCalendarEvent,
    HrPosition,
    HrRecruitmentCandidate,
)


def _legacy_dashboard_reference(db, factory):
    employees = db.query(Employee).filter(Employee.factory_code == factory).all()
    active = [row for row in employees if row.status == "active"]
    positions = db.query(HrPosition).filter(
        HrPosition.factory_code == factory,
        HrPosition.is_active.is_(True),
    ).all()
    department_names = {row.id: row.name for row in db.query(Department).all()}
    by_department = {}
    for employee in active:
        name = department_names.get(employee.department_id, "Unassigned")
        by_department[name] = by_department.get(name, 0) + 1
    return {
        "headcount": len(active),
        "inactive": len(employees) - len(active),
        "approved_positions": sum(row.approved_count for row in positions),
        "vacancies": max(0, sum(row.approved_count for row in positions) - len(active)),
        "candidates": db.query(HrRecruitmentCandidate).filter(
            HrRecruitmentCandidate.factory_code == factory,
        ).count(),
        "upcoming_events": db.query(HrCalendarEvent).filter(
            HrCalendarEvent.factory_code == factory,
            HrCalendarEvent.starts_at >= datetime.now(timezone.utc),
        ).count(),
        "by_department": [
            {"name": name, "count": count}
            for name, count in sorted(by_department.items())
        ],
    }


@pytest.mark.parametrize("employee_count", [1, 50, 401])
def test_hr_dashboard_aggregates_factory_rows_in_sql_with_legacy_parity(employee_count):
    factory = "ECO"
    suffix = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        department = Department(name=f"PERF35 HR {suffix}", code=f"H{suffix}")
        db.add(department)
        db.flush()
        employees = [
            Employee(
                factory_code=factory,
                employee_no=f"PERF35-{suffix}-{index:04d}",
                full_name=f"Dashboard employee {index}",
                department_id=None if index % 5 == 0 else department.id,
                status="inactive" if index % 3 == 0 else "active",
            )
            for index in range(employee_count)
        ]
        db.add_all(
            [
                *employees,
                HrPosition(factory_code=factory, name=f"Active {suffix}", approved_count=7),
                HrPosition(factory_code=factory, name=f"Inactive {suffix}", approved_count=900, is_active=False),
                HrPosition(factory_code="BST", name=f"Other factory {suffix}", approved_count=500),
                HrRecruitmentCandidate(factory_code=factory, full_name=f"Candidate {suffix}"),
                HrCalendarEvent(
                    factory_code=factory,
                    event_type="training",
                    title=f"Event {suffix}",
                    starts_at=datetime.now(timezone.utc) + timedelta(days=2),
                ),
            ]
        )
        db.commit()

    with SessionLocal() as db:
        expected = _legacy_dashboard_reference(db, factory)
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            actual = dashboard(
                db,
                SimpleNamespace(factory_code=factory, role=None, extra_permissions=[]),
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert actual == expected
    assert len(statements) == 4, statements
    employee_query = next(statement for statement in statements if " from employees " in statement)
    assert "group by coalesce(departments.name, ?)" in employee_query
    assert "employees.status" in employee_query
    assert "employees.full_name" not in employee_query
    assert all(" from departments" not in statement for statement in statements)
    positions_query = next(statement for statement in statements if " from hr_positions " in statement)
    assert "sum(hr_positions.approved_count)" in positions_query
