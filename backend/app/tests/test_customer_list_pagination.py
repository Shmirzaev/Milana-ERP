from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.partners import list_customers
from app.models import AuditLog, Customer
from app.tests.conftest import TestSessionLocal


@contextmanager
def _customer_database(count: int):
    engine = create_engine("sqlite://")
    Customer.__table__.create(engine)
    with Session(engine) as db:
        marker = uuid4().hex[:10]
        rows = [
            Customer(
                name=f"PERF35 customer {marker} {index:04d}",
                phone=f"+99890{index:07d}",
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
        payload = list_customers(db, object(), q=marker, **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_customer_pages_bound_sql_and_preserve_legacy_payload(count):
    with _customer_database(count) as (db, marker, created_ids):
        page, statements = _read(db, marker, page=1, page_size=50)
        legacy, legacy_statements = _read(db, marker)

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


def test_customer_page_contract_auth_compatibility_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        rows = [Customer(name=f"PERF35 customer {marker} {index}") for index in range(3)]
        db.add_all(rows)
        db.commit()
        created_ids = [int(row.id) for row in rows]
        before = (db.query(Customer).count(), db.query(AuditLog).count())

    legacy = client.get("/api/customers", params={"q": marker}, headers=auth_headers)
    paged = client.get(
        "/api/customers",
        params={"q": marker, "page": 1, "page_size": 2},
        headers=auth_headers,
    )
    compatible = client.get(
        "/api/customers",
        params={"q": marker, "include_total": "true", "page": 1, "page_size": 2},
        headers=auth_headers,
    )
    legacy_clamped = client.get(
        "/api/customers",
        params={"q": marker, "include_total": "true", "page": 0, "page_size": 501},
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
    assert client.get("/api/customers?page=1&page_size=1").status_code == 401
    assert client.get(
        "/api/customers?page_size=501",
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    denied = client.get(
        "/api/customers?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403, denied.text

    with TestSessionLocal() as db:
        after = (db.query(Customer).count(), db.query(AuditLog).count())
    assert after == before
