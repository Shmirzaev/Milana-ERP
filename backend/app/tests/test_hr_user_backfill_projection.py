from sqlalchemy import event

from app.api.routes.hr import _backfill_employees_from_users
from app.models import Employee, User
from app.tests.conftest import TestSessionLocal, test_engine


def test_employee_backfill_projects_only_employee_source_fields():
    with TestSessionLocal() as db:
        existing_user_ids = {
            int(user_id)
            for (user_id,) in db.query(Employee.user_id).filter(Employee.user_id.isnot(None)).all()
        }
        users = db.query(User.id, User.name, User.factory_code).all()
        db.add_all(
            Employee(
                factory_code=factory_code,
                user_id=user_id,
                full_name=name,
            )
            for user_id, name, factory_code in users
            if int(user_id) not in existing_user_ids
        )
        db.commit()

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            assert _backfill_employees_from_users(db) == 0
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)

    user_reads = [statement for statement in statements if " from users " in statement]
    assert len(user_reads) == 1
    assert "users.name" in user_reads[0]
    assert "users.factory_code" in user_reads[0]
    assert "roles_1.name" in user_reads[0]
    assert "users.password_hash" not in user_reads[0]
    assert "roles_1.permissions" not in user_reads[0]
    assert "departments" not in user_reads[0]
