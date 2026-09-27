from uuid import uuid4

from sqlalchemy import event

from app.api.routes.notifications import NotificationSendIn, _resolve_recipients
from app.models import Department, User
from app.tests.conftest import TestSessionLocal, test_engine


def test_department_notification_recipient_lookup_projects_only_department_id():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        department = Department(name=f"Recipient team {marker}", code=f"T{marker[:2]}")
        db.add(department)
        db.flush()
        active_user = User(
            name=f"Active recipient {marker}",
            email=f"active-{marker}@example.test",
            password_hash="unused-test-hash",
            department_id=department.id,
            is_active=True,
        )
        inactive_user = User(
            name=f"Inactive recipient {marker}",
            email=f"inactive-{marker}@example.test",
            password_hash="unused-test-hash",
            department_id=department.id,
            is_active=False,
        )
        db.add_all([active_user, inactive_user])
        db.commit()
        active_user_id = active_user.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            recipients = _resolve_recipients(
                NotificationSendIn(target_type="department", department=f"  t{marker[:2]}  ", title="Notice"),
                db,
            )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert [recipient.id for recipient in recipients] == [active_user_id]
    department_reads = [statement for statement in statements if " from departments " in statement]
    assert len(department_reads) == 1, statements
    assert department_reads[0].startswith(
        "select departments.id as departments_id from departments where "
    )
    assert "departments.name" not in department_reads[0].split(" from ", 1)[0]
    user_reads = [statement for statement in statements if " from users " in statement]
    assert len(user_reads) == 1, statements
    user_columns = user_reads[0].split(" from ", 1)[0]
    assert "users.name" in user_columns
    assert "users.is_active" in user_columns
    assert "users.password_hash" not in user_columns
