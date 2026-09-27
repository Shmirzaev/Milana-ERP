from uuid import uuid4

from sqlalchemy import event

from app.api.routes.hr import _validate_employee_references
from app.models import Employee, HrPosition
from app.tests.conftest import TestSessionLocal


def test_hr_manager_and_position_reference_checks_select_only_ids():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        manager = Employee(
            factory_code="MIL",
            employee_no=f"MGR-{marker}",
            full_name=f"Manager {marker}",
        )
        position = HrPosition(
            factory_code="MIL",
            name=f"Position {marker}",
        )
        db.add_all([manager, position])
        db.flush()

        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and (
                " from employees " in normalized or " from hr_positions " in normalized
            ):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            _validate_employee_references(
                db,
                "MIL",
                user_id=None,
                department_id=None,
                manager_employee_id=manager.id,
                hr_position_id=position.id,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert len(statements) == 2, statements
    employee_query = next(statement for statement in statements if " from employees " in statement)
    position_query = next(statement for statement in statements if " from hr_positions " in statement)
    assert "select employees.id " in employee_query
    assert "select hr_positions.id " in position_query
    assert "employees.full_name" not in employee_query
    assert "hr_positions.job_description" not in position_query
