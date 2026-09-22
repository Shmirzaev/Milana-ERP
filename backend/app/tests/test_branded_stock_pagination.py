from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.routes.finished_goods import list_branded
from app.models import AuditLog, Brand, FinishedGoodsStock, Model, Package, ProductionOrder
from app.tests.conftest import TestSessionLocal


@contextmanager
def _stock_database(count: int):
    engine = create_engine("sqlite://")
    for model in (Brand, Model, ProductionOrder, Package, FinishedGoodsStock):
        model.__table__.create(engine)
    with Session(engine) as db:
        rows = [
            FinishedGoodsStock(
                model_id=1,
                brand_id=1,
                color="Black",
                size=f"S{index:04d}",
                quantity=1,
                available_qty=1,
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=1,
                selling_price=2,
                status="available",
            )
            for index in range(count)
        ]
        db.add_all(rows)
        db.commit()
        yield db, [int(row.id) for row in rows]
    engine.dispose()


def _read(db: Session, **kwargs):
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(db.bind, "before_cursor_execute", capture)
    try:
        payload = list_branded(db, object(), **kwargs)
    finally:
        event.remove(db.bind, "before_cursor_execute", capture)
    return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_branded_stock_pages_bound_sql_and_preserve_legacy_payload(count):
    with _stock_database(count) as (db, created_ids):
        page, statements = _read(db, limit=500, offset=0, page=1, page_size=50)
        legacy, legacy_statements = _read(db, limit=500, offset=0, page=None, page_size=None)
        expected_count = min(count, 50)

        assert page["total"] == count
        assert page["page"] == 1
        assert page["page_size"] == 50
        assert page["has_more"] is (count > 50)
        assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))[:expected_count]
        assert page["rows"] == legacy[:expected_count]
        assert len(statements) == 2, statements
        assert " limit ? offset ?" in statements[1]
        assert len(legacy_statements) == 1, legacy_statements


def test_branded_stock_page_contract_auth_bounds_and_no_writes(client, auth_headers):
    with TestSessionLocal() as db:
        model = db.query(Model).order_by(Model.id).first()
        brand = db.query(Brand).order_by(Brand.id).first()
        assert model is not None
        assert brand is not None
        stock = FinishedGoodsStock(
            model_id=model.id,
            brand_id=brand.id,
            color="PERF35",
            size="ONE",
            quantity=1,
            available_qty=1,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=1,
            selling_price=2,
            status="available",
        )
        db.add(stock)
        db.commit()
        stock_id = int(stock.id)
        before = (db.query(FinishedGoodsStock).count(), db.query(AuditLog).count())

    legacy = client.get("/api/finished-goods/branded-stock?limit=1", headers=auth_headers)
    assert legacy.status_code == 200, legacy.text
    assert [row["id"] for row in legacy.json()] == [stock_id]

    response = client.get(
        "/api/finished-goods/branded-stock?page=1&page_size=1",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rows"] == legacy.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] >= 1
    assert payload["has_more"] is (payload["total"] > 1)

    assert client.get(
        "/api/finished-goods/branded-stock?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get("/api/finished-goods/branded-stock?page=1&page_size=1").status_code == 401

    with TestSessionLocal() as db:
        after = (db.query(FinishedGoodsStock).count(), db.query(AuditLog).count())
    assert after == before
