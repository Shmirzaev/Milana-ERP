from uuid import uuid4

from sqlalchemy import event

from app.api.routes import admin
from app.models import Department, Role, User
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_membership_cases() -> int:
    marker = uuid4().hex
    with TestSessionLocal() as db:
        department = db.query(Department).filter(Department.code == "STR").first()
        wildcard_role = Role(name=f"Projection wildcard {marker}", permissions=["*"])
        db.add(wildcard_role)
        db.flush()
        users = [
            User(
                name=f"Projection role admin {marker}",
                email=f"projection-role-{marker}@example.invalid",
                password_hash="unused",
                role_id=wildcard_role.id,
                department_id=department.id,
                factory_code="MIL",
                extra_permissions=[],
                is_active=True,
            ),
            User(
                name=f"Projection super admin {marker}",
                email=f"projection-super-{marker}@example.invalid",
                password_hash="unused",
                factory_code="MIL",
                extra_permissions=["admin.super"],
                is_active=True,
            ),
            User(
                name=f"Projection policy admin {marker}",
                email=f"projection-policy-{marker}@example.invalid",
                password_hash="unused",
                factory_code="MIL",
                extra_permissions=["*"],
                access_policy={"MIL": {"deny": ["*"]}},
                is_active=True,
            ),
            User(
                name=f"Projection inactive admin {marker}",
                email=f"projection-inactive-{marker}@example.invalid",
                password_hash="unused",
                factory_code="MIL",
                extra_permissions=["*", "admin.super"],
                is_active=False,
            ),
        ]
        db.add_all(users)
        db.commit()
        return users[0].id


def _reference_counts(exclude_user_id: int | None = None) -> tuple[int, int]:
    with TestSessionLocal() as db:
        active_users = db.query(User).filter(User.is_active.is_(True)).all()
        if exclude_user_id is not None:
            active_users = [user for user in active_users if user.id != exclude_user_id]
        return (
            sum("*" in admin.user_permissions(user) for user in active_users),
            sum(admin.is_super_admin(user) for user in active_users),
        )


def test_admin_membership_counts_project_columns_without_deferred_selects():
    excluded_user_id = _seed_membership_cases()
    expected = _reference_counts(excluded_user_id)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            actual = (
                admin._count_active_admins(db, excluded_user_id),
                admin._count_active_super_admins(db, excluded_user_id),
            )
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert actual == expected
    assert len(statements) == 2, statements
    for statement in statements:
        selected_columns = statement.split(" from users", 1)[0]
        assert "users.password_hash" not in selected_columns
        assert "users.email" not in selected_columns
        assert "users.last_login_at" not in selected_columns
        assert ".permissions as roles_1_permissions" in selected_columns
        assert ".code as departments_1_code" in selected_columns
