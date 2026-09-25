from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.catalog import list_brands
from app.models import AuditLog, Brand
from app.schemas.catalog import BrandOut
from app.tests.conftest import TestSessionLocal


@contextmanager
def _brand_database(count: int):
    engine = create_engine("sqlite://")
    Brand.__table__.create(engine)
    with Session(engine) as db:
        db.add_all(
            Brand(name=f"Brand {index:04d}", description=f"Description {index}")
            for index in range(count)
        )
        db.commit()
        yield db
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_brands(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


def _payload(rows: list[Brand]) -> list[dict]:
    return [BrandOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_brand_pages_bound_sql_and_preserve_legacy_payload(count):
    with _brand_database(count) as db:
        page, statements = _read(db, limit=500, page=1, page_size=50)
        legacy, legacy_statements = _read(db, limit=500, page=None, page_size=None)

        expected_count = min(count, 50)
        assert page["total"] == count
        assert page["page"] == 1
        assert page["page_size"] == 50
        assert page["has_more"] is (count > 50)
        assert len(page["rows"]) == expected_count
        assert [row.name for row in page["rows"]] == [f"Brand {index:04d}" for index in range(expected_count)]
        assert _payload(page["rows"]) == _payload(legacy[:expected_count])
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_brand_page_contract_authentication_bounds_and_no_writes(client, auth_headers):
    with TestSessionLocal() as db:
        before = (db.query(Brand).count(), db.query(AuditLog).count())

    legacy = client.get("/api/brands?limit=1", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 1

    response = client.get("/api/brands?page=1&page_size=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"] == legacy.json()
    assert payload["total"] >= 1
    assert payload["has_more"] is (payload["total"] > 1)

    assert client.get("/api/brands?page=1&page_size=501", headers=auth_headers).status_code == 422
    assert client.get("/api/brands?page=1&page_size=1").status_code == 401

    with TestSessionLocal() as db:
        after = (db.query(Brand).count(), db.query(AuditLog).count())
    assert after == before


def test_brand_search_filters_before_paging_and_escapes_like_wildcards():
    with _brand_database(401) as db:
        db.add(Brand(name="Brand %_ literal", description="Special marker"))
        db.commit()

        page, statements = _read(db, page=2, page_size=50, q="Brand 03")
        assert page["total"] == 100
        assert page["has_more"] is False
        assert [row.name for row in page["rows"]] == [f"Brand {index:04d}" for index in range(350, 400)]
        assert len(statements) == 2

        description, _ = _read(db, page=1, page_size=50, q="Description 399")
        assert description["total"] == 1
        assert description["rows"][0].name == "Brand 0399"

        literal, _ = _read(db, page=1, page_size=50, q="%_")
        assert literal["total"] == 1
        assert literal["rows"][0].name == "Brand %_ literal"


def test_brand_id_lookup_keeps_visible_collection_brands_outside_first_page(client, auth_headers):
    with _brand_database(401) as db:
        selected_ids = [
            int(row.id)
            for row in db.query(Brand.id).filter(Brand.name.in_(("Brand 0000", "Brand 0400"))).all()
        ]
        page, _ = _read(db, page=1, page_size=50, ids=selected_ids)
        assert page["total"] == 2
        assert [row.name for row in page["rows"]] == ["Brand 0000", "Brand 0400"]

    response = client.get(
        "/api/brands",
        params=[("page", "1"), ("page_size", "50"), *(("ids", str(index)) for index in range(1, 102))],
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text
