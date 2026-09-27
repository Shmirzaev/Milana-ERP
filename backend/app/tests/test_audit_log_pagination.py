from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.admin import list_audit_logs
from app.models import AuditLog, Department, Role, User
from app.tests.conftest import TestSessionLocal


@contextmanager
def _audit_database(count: int):
    engine = create_engine("sqlite://")
    Role.__table__.create(engine)
    Department.__table__.create(engine)
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    with Session(engine) as db:
        marker = f"Perf35Audit{uuid4().hex[:10]}"
        rows = [
            AuditLog(
                action="read",
                entity_type=marker,
                entity_id=index,
                new_value_json={"index": index},
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        yield db, marker, [int(row.id) for row in rows]
    engine.dispose()


def _read(db: Session, marker: str, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_audit_logs(db, object(), entity_type=marker, **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_audit_log_pages_bound_sql_and_preserve_legacy_payload(count):
    with _audit_database(count) as (db, marker, created_ids):
        page, statements = _read(db, marker, page=1, page_size=50)
        legacy, legacy_statements = _read(db, marker, limit=500)

        selects = [statement for statement in statements if statement.startswith("select")]
        writes = [
            statement
            for statement in statements
            if statement.startswith(("insert", "update", "delete"))
        ]
        assert page == {
            "rows": legacy[:50],
            "total": count,
            "page": 1,
            "page_size": 50,
        }
        assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:50]
        assert len(selects) == 2, selects
        assert " limit ? offset ?" in selects[1]
        assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 1
        assert writes == []


def test_audit_log_page_contract_auth_compatibility_and_no_writes(client, auth_headers):
    marker = f"Perf35Audit{uuid4().hex[:10]}"
    with TestSessionLocal() as db:
        rows = [
            AuditLog(action="read", entity_type=marker, entity_id=index)
            for index in range(3)
        ]
        db.add_all(rows)
        db.commit()
        created_ids = [int(row.id) for row in rows]

    legacy = client.get(
        "/api/audit-logs",
        params={"entity_type": marker, "limit": 10},
        headers=auth_headers,
    )
    paged = client.get(
        "/api/audit-logs",
        params={"entity_type": marker, "page": 1, "page_size": 2},
        headers=auth_headers,
    )
    compatible = client.get(
        "/api/audit-logs",
        params={"entity_type": marker, "include_total": "true", "page": 1, "page_size": 2},
        headers=auth_headers,
    )
    legacy_clamped = client.get(
        "/api/audit-logs",
        params={"entity_type": marker, "include_total": "true", "page": 0, "page_size": 501},
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == compatible.status_code == 200
    expected = {
        "rows": legacy.json()[:2],
        "total": 3,
        "page": 1,
        "page_size": 2,
    }
    assert paged.json() == compatible.json() == expected
    assert [row["id"] for row in paged.json()["rows"]] == list(reversed(created_ids))[:2]
    assert legacy_clamped.status_code == 200
    assert legacy_clamped.json() == {
        "rows": legacy.json(),
        "total": 3,
        "page": 1,
        "page_size": 500,
    }
    assert client.get("/api/audit-logs?page=1&page_size=1").status_code == 401
    assert client.get(
        "/api/audit-logs?page_size=501",
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/audit-logs?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        assert db.query(AuditLog).filter(AuditLog.entity_type == marker).count() == 3
