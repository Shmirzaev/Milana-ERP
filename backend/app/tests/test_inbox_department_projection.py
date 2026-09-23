from types import SimpleNamespace

from sqlalchemy import event

from app.api.routes.inbox import _resolve_department
from app.tests.conftest import TestSessionLocal


def test_inbox_department_resolution_projects_only_id_and_code():
    current = SimpleNamespace(
        factory_code="MIL",
        session_factory_code="MIL",
        extra_permissions=[],
        access_policy={},
        role=None,
    )
    with TestSessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from departments " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            department = _resolve_department(db, current, "CUT")
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert department.code == "CUT"
    assert department.id > 0
    assert len(statements) == 1, statements
    assert "departments.id" in statements[0]
    assert "departments.code" in statements[0]
    assert "departments.name" not in statements[0]
