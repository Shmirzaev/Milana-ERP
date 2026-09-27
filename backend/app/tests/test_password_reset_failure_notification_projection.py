"""Reset-email failure notifications load only fields used for authorization and copy."""
from uuid import uuid4

from sqlalchemy import event

from app.models import Notification, Role, User
from app.services import password_reset
from app.tests.conftest import TestSessionLocal, test_engine


def test_failure_notice_projects_user_role_and_department_fields(monkeypatch):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        role = Role(name=f"Projection admin {marker}", permissions=["admin.users"])
        db.add(role)
        db.flush()
        admin = User(
            name=f"Projection admin {marker}", email=f"projection-admin-{marker}@example.invalid",
            password_hash="unused", role_id=role.id, is_active=True,
        )
        target = User(
            name=f"Projection target {marker}", email=f"projection-target-{marker}@example.invalid",
            password_hash="unused", is_active=True,
        )
        db.add_all([admin, target])
        db.commit()
        admin_id = int(admin.id)
        target_id = int(target.id)

    monkeypatch.setattr(password_reset, "SessionLocal", TestSessionLocal)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from users " in normalized:
            statements.append(normalized)

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        password_reset.notify_admins_about_password_email_failure(
            target_id, "https://example.invalid/reset-password?token=secret", "provider failed",
        )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert len(statements) == 2, statements
    target_lookup = next(sql for sql in statements if "where users.id = ?" in sql)
    target_columns = target_lookup.split(" from users ", maxsplit=1)[0]
    assert "users.id" in target_columns
    assert "users.name" in target_columns
    assert "users.email" in target_columns
    assert "users.password_hash" not in target_columns
    assert " join " not in target_lookup

    recipient_lookup = next(sql for sql in statements if "where users.is_active" in sql)
    recipient_columns = recipient_lookup.split(" from users ", maxsplit=1)[0]
    for omitted in ("users.password_hash", "users.last_login_at", "roles_1.created_at", "departments_1.name"):
        assert omitted not in recipient_columns
    assert "users.extra_permissions" in recipient_columns
    assert "roles_1.permissions" in recipient_columns
    assert "departments_1.code" in recipient_columns

    with TestSessionLocal() as db:
        assert db.query(Notification).filter_by(user_id=admin_id).filter(
            Notification.title == "Password reset email failed",
        ).count() == 1
