from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.catalog import list_collections
from app.models import AuditLog, Brand, Collection
from app.tests.conftest import TestSessionLocal


@contextmanager
def _collection_database(count: int):
    engine = create_engine("sqlite://")
    Brand.__table__.create(engine)
    Collection.__table__.create(engine)
    with Session(engine) as db:
        brand = Brand(name="Paged collections")
        db.add(brand)
        db.flush()
        db.add_all([
            Collection(
                brand_id=brand.id,
                name=f"Collection {index:04d}",
                season=f"Season {index:04d}",
                year=2090,
                status="draft",
            )
            for index in range(count)
        ])
        db.commit()
        yield db, int(brand.id)
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_collections(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_collection_pages_bound_sql_and_preserve_legacy_payload(count):
    with _collection_database(count) as (db, brand_id):
        page, statements = _read(
            db,
            brand_id=brand_id,
            page=1,
            page_size=50,
        )
        legacy, legacy_statements = _read(
            db,
            brand_id=brand_id,
            page=None,
            page_size=None,
        )

        selects = [statement for statement in statements if statement.startswith("select")]
        writes = [
            statement for statement in statements
            if statement.startswith(("insert", "update", "delete"))
        ]
        assert page == {
            "rows": legacy[:50],
            "total": count,
            "page": 1,
            "page_size": 50,
        }
        assert len(page["rows"]) == min(count, 50)
        assert len(selects) == 2, selects
        assert " limit ? offset ?" in selects[1]
        assert len([statement for statement in legacy_statements if statement.startswith("select")]) == 1
        assert writes == []


def test_collection_page_contract_auth_filter_and_no_writes(client, auth_headers):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        brand = Brand(name=f"PERF35 collection brand {marker}")
        db.add(brand)
        db.flush()
        db.add(Collection(
            brand_id=brand.id,
            name=f"PERF35 collection {marker}",
            season="Winter",
            year=2099,
            status="draft",
        ))
        db.commit()
        brand_id = int(brand.id)
        before = (db.query(Collection).count(), db.query(AuditLog).count())

    legacy = client.get(
        "/api/collections",
        params={"brand_id": brand_id},
        headers=auth_headers,
    )
    paged = client.get(
        "/api/collections",
        params={"brand_id": brand_id, "page": 1, "page_size": 50},
        headers=auth_headers,
    )
    compatible = client.get(
        "/api/collections",
        params={"brand_id": brand_id, "include_total": "true"},
        headers=auth_headers,
    )
    legacy_clamped = client.get(
        "/api/collections",
        params={
            "brand_id": brand_id,
            "include_total": "true",
            "page": 0,
            "page_size": 501,
        },
        headers=auth_headers,
    )

    assert legacy.status_code == paged.status_code == compatible.status_code == 200
    assert paged.json() == compatible.json() == {
        "rows": legacy.json(),
        "total": 1,
        "page": 1,
        "page_size": 50,
    }
    assert legacy_clamped.status_code == 200
    assert legacy_clamped.json() == {
        "rows": legacy.json(),
        "total": 1,
        "page": 1,
        "page_size": 500,
    }
    assert client.get("/api/collections?page=1&page_size=1").status_code == 401
    assert client.get(
        "/api/collections?page_size=501",
        headers=auth_headers,
    ).status_code == 422

    login = client.post(
        "/api/auth/token",
        data={"username": "hr@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    allowed = client.get(
        "/api/collections?page=1&page_size=1",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert allowed.status_code == 200, allowed.text

    with TestSessionLocal() as db:
        after = (db.query(Collection).count(), db.query(AuditLog).count())
    assert after == before
