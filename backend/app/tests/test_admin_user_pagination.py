from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.admin import list_users
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import AuditLog, Role, User
from app.schemas.catalog import UserOut


def _seed_users(count: int) -> tuple[list[int], int]:
    marker = uuid4().hex
    with SessionLocal() as db:
        baseline = db.query(User).count()
        users = [
            User(
                name=f"Paged user {marker} {index:04d}",
                email=f"paged-user-{marker}-{index:04d}@example.com",
                password_hash="unused-pagination-hash",
                factory_code="MIL",
                extra_permissions=["tasks.view"] if index % 2 else [],
                is_active=True,
            )
            for index in range(count)
        ]
        db.add_all(users)
        db.commit()
        return [int(user.id) for user in users], baseline


def _read(**kwargs):
    with SessionLocal() as db:
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_users(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


def _payload(rows: list[User]) -> list[dict]:
    return [UserOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("row_count", [1, 50, 401])
def test_user_page_bounds_sql_and_preserves_legacy_prefix(row_count):
    created_ids, baseline = _seed_users(row_count)

    legacy, legacy_statements = _read(limit=500)
    page, page_statements = _read(page=1, page_size=50)

    assert page["total"] == baseline + row_count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is ((baseline + row_count) > 50)
    assert len(page["rows"]) <= 50
    assert _payload(page["rows"]) == _payload(legacy[:50])
    assert created_ids == [row.id for row in legacy[-row_count:]]
    assert len(legacy_statements) == 1, legacy_statements
    assert len(page_statements) == 2, page_statements
    row_statement = next(statement for statement in page_statements if " limit ? offset ?" in statement)
    assert "order by users.id" in row_statement
    selected_columns = row_statement.split(" from users", 1)[0]
    for unrelated in ("users.password_hash", "users.tokens_valid_from", "users.updated_at"):
        assert unrelated not in selected_columns
    assert " join roles " not in row_statement
    assert " join departments " not in row_statement


def test_user_page_contract_permission_auth_and_no_writes(client, auth_headers):
    _created_ids, baseline = _seed_users(3)
    with SessionLocal() as db:
        role = Role(name=f"No user admin {uuid4().hex}", permissions=[])
        db.add(role)
        db.flush()
        denied_user = User(
            name="Denied user reader",
            email=f"denied-user-reader-{uuid4().hex}@example.com",
            password_hash="unused-pagination-hash",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        db.add(denied_user)
        db.commit()
        denied_headers = {"Authorization": f"Bearer {create_access_token(denied_user.id)}"}
        before = (db.query(User).count(), db.query(AuditLog).count())

    legacy = client.get("/api/users", params={"limit": 1}, headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 1

    paged = client.get(
        "/api/users",
        params={"page": 1, "page_size": 1},
        headers=auth_headers,
    )
    assert paged.status_code == 200, paged.text
    payload = paged.json()
    assert payload["rows"] == legacy.json()
    assert payload["total"] == baseline + 4
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["has_more"] is True

    assert client.get(
        "/api/users",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/users",
        params={"page": 1, "page_size": 1},
        headers=denied_headers,
    ).status_code == 403
    assert client.get(
        "/api/users",
        params={"page": 1, "page_size": 1},
    ).status_code == 401

    with SessionLocal() as db:
        after = (db.query(User).count(), db.query(AuditLog).count())
    assert after == before
