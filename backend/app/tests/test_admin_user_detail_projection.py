from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.admin import get_user
from app.models import Department, Role, User
from app.schemas.catalog import UserOut
from app.tests.conftest import TestSessionLocal, test_engine


def test_admin_user_detail_projects_only_response_fields():
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        role = Role(name=f"Projection role {marker}", permissions=["admin.users"])
        department = Department(name=f"Projection dept {marker}", code=f"P{marker[:2]}")
        db.add_all([role, department])
        db.flush()
        user = User(
            name=f"Projection user {marker}",
            email=f"projection-{marker}@example.test",
            password_hash="unused-test-hash",
            role_id=role.id,
            department_id=department.id,
            extra_permissions=["admin.users"],
        )
        db.add(user)
        db.commit()
        user_id = user.id

    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        with TestSessionLocal() as db:
            result = UserOut.model_validate(get_user(user_id, db, _=None))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert result.id == user_id
    assert result.name == f"Projection user {marker}"
    assert result.email == f"projection-{marker}@example.test"
    assert result.extra_permissions == ["admin.users"]
    assert len(statements) == 1, statements
    selected_columns = statements[0].split(" from users ", 1)[0]
    assert "users.name" in selected_columns
    assert "users.created_at" in selected_columns
    assert "users.password_hash" not in selected_columns
    assert " join roles " not in statements[0]
    assert " join departments " not in statements[0]

    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            get_user(user_id + 1_000_000_000, db, _=None)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "User not found"
