from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.models import Model, Notification, Role, User
from app.core.deps import user_permissions
from app.services.price_calculation import _notify_finance, is_finance_pricing_user
from app.tests.conftest import TestSessionLocal


def test_price_calculation_finance_notifications_project_user_policy_fields():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        finance_role = Role(name=f"PERF35 finance {marker}", permissions=["finance.view"])
        other_role = Role(name=f"PERF35 other {marker}", permissions=["sales.orders"])
        db.add_all([finance_role, other_role])
        db.flush()
        finance_user = User(
            name="Finance recipient",
            email=f"finance-{marker}@example.test",
            password_hash="unused",
            role_id=finance_role.id,
        )
        other_user = User(
            name="Other recipient",
            email=f"other-{marker}@example.test",
            password_hash="unused",
            role_id=other_role.id,
        )
        inactive_finance_user = User(
            name="Inactive finance recipient",
            email=f"inactive-{marker}@example.test",
            password_hash="unused",
            role_id=finance_role.id,
            is_active=False,
        )
        model = Model(code=f"PERF35-PC-{marker}", name="Price model", status="approved")
        db.add_all([finance_user, other_user, inactive_finance_user, model])
        db.commit()
        expected_recipient_ids = {
            int(user.id)
            for user in db.query(User).filter(User.is_active.is_(True)).all()
            if is_finance_pricing_user(user) and "*" not in user_permissions(user)
        }

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from users " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            _notify_finance(
                db,
                SimpleNamespace(model=model),
                "Cutting details completed",
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        db.flush()
        notifications = db.query(Notification).filter(
            Notification.title == "Cutting details completed",
            Notification.message == f"Model {model.code} price request was updated.",
        ).all()

    assert {int(row.user_id) for row in notifications} == expected_recipient_ids
    assert int(finance_user.id) in expected_recipient_ids
    assert int(inactive_finance_user.id) not in expected_recipient_ids
    assert len(statements) == 1
    assert "users.is_active" in statements[0]
    assert "roles_1.permissions" in statements[0]
    assert "roles_1.name" in statements[0]
    assert "departments_1.code" in statements[0]
    for omitted in (
        "users.password_hash",
        "users.email",
        "users.last_login_at",
        "users.last_seen_at",
    ):
        assert omitted not in statements[0]
