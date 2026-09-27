from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.catalog import list_collection_seasons
from app.models import AuditLog, Brand, Collection
from app.tests.conftest import TestSessionLocal


@contextmanager
def _collection_database(count: int):
    engine = create_engine("sqlite://")
    Collection.__table__.create(engine)
    with Session(engine) as db:
        db.add_all(
            Collection(
                brand_id=1,
                name=f"Collection {index:04d}",
                season=f"Season {index:04d}",
                year=2090,
                status="draft",
            )
            for index in range(count)
        )
        db.commit()
        yield db
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_collection_seasons(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_collection_season_pages_bound_sql_and_preserve_legacy_payload(count):
    with _collection_database(count) as db:
        page, statements = _read(db, page=1, page_size=50)
        legacy, legacy_statements = _read(db, page=None, page_size=None)
        expected_count = min(count, 50)
        expected = [f"Season {index:04d}" for index in range(expected_count)]

        assert page == {
            "rows": expected,
            "total": count,
            "page": 1,
            "page_size": 50,
            "has_more": count > 50,
        }
        assert page["rows"] == legacy[:expected_count]
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_collection_season_page_contract_auth_bounds_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        brand = Brand(name=f"PERF35 season brand {marker}")
        db.add(brand)
        db.flush()
        db.add(Collection(
            brand_id=brand.id,
            name=f"PERF35 season collection {marker}",
            season=f"!!! PERF35 {marker}",
            year=2099,
            status="draft",
        ))
        db.commit()
        before = (db.query(Collection).count(), db.query(AuditLog).count())

    legacy = client.get("/api/collections/seasons", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)

    response = client.get(
        "/api/collections/seasons?page=1&page_size=50",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == legacy.json()[:50]
    assert payload["total"] == len(legacy.json())
    assert payload["page"] == 1
    assert payload["page_size"] == 50
    assert payload["has_more"] is (payload["total"] > 50)

    assert client.get(
        "/api/collections/seasons?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/collections/seasons?page=1&page_size=1").status_code == 401

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    allowed = client.get(
        "/api/collections/seasons?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert allowed.status_code == 200, allowed.text

    with TestSessionLocal() as db:
        after = (db.query(Collection).count(), db.query(AuditLog).count())
    assert after == before
