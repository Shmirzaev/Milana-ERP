from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.finished_goods import list_branded, list_stock
from app.models import Brand, FinishedGoodsStock, Model
from app.tests.conftest import TestSessionLocal, test_engine


def _seed_stock(count, *, status="damaged"):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        brand = Brand(name=f"Bounded stock brand {marker}", is_active=True)
        models = [
            Model(
                code=f"FG-{marker}-{index:04d}",
                name=f"Bounded stock model {index}",
                status="approved",
            )
            for index in range(count)
        ]
        db.add_all([brand, *models])
        db.flush()
        stocks = [
            FinishedGoodsStock(
                model_id=model.id,
                brand_id=brand.id,
                color="Blue",
                size="M",
                quantity=1,
                available_qty=1,
                reserved_qty=0,
                sold_qty=0,
                cost_per_piece=1,
                selling_price=2,
                status=status,
            )
            for model in models
        ]
        db.add_all(stocks)
        db.commit()
        return int(brand.id), [int(stock.id) for stock in stocks], [model.code for model in models]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_stock(db, object(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


def _read_branded(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_branded(db, object(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_finished_goods_pages_preserve_legacy_and_bound_joined_enrichment(count):
    brand_id, stock_ids, model_codes = _seed_stock(count)
    returned_count = min(count, 50)

    page, statements = _read(
        status="damaged",
        brand_id=brand_id,
        page=1,
        page_size=50,
    )
    legacy, _ = _read(status="damaged", brand_id=brand_id, limit=500, offset=0)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(stock_ids))[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert [row["model_code"] for row in page["rows"]] == list(reversed(model_codes))[:returned_count]
    assert all(row["brand_name"].startswith("Bounded stock brand ") for row in page["rows"])
    assert len(statements) == 2, statements
    row_query = statements[1]
    assert "left outer join models" in row_query
    assert "left outer join brands" in row_query
    assert " limit ? offset ?" in row_query


@pytest.mark.parametrize("count", [1, 50, 401])
def test_branded_stock_pages_preserve_legacy_and_bound_joined_enrichment(count):
    baseline, _ = _read_branded(limit=500, offset=0)
    _brand_id, stock_ids, model_codes = _seed_stock(count, status="available")

    page, statements = _read_branded(page=1, page_size=50)
    legacy, _ = _read_branded(limit=500, offset=0)
    returned_count = min(count, 50)

    assert page["total"] == len(baseline) + count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page["rows"]] == list(reversed(stock_ids))[:returned_count]
    assert page["rows"] == legacy[:returned_count]
    assert [row["model_code"] for row in page["rows"]] == list(reversed(model_codes))[:returned_count]
    assert all(row["brand_name"].startswith("Bounded stock brand ") for row in page["rows"])
    assert len(statements) == 2, statements
    assert " limit ? offset ?" in statements[1]


def test_finished_goods_search_filters_are_exact_and_escape_wildcards():
    _brand_id, stock_ids, model_codes = _seed_stock(2)

    stock_page, _ = _read(q=model_codes[0], page=1, page_size=50)
    assert stock_page["total"] == 1
    assert [row["id"] for row in stock_page["rows"]] == [stock_ids[0]]

    literal_wildcard_page, _ = _read(q="%", page=1, page_size=50)
    assert literal_wildcard_page["total"] == 0


def test_finished_goods_page_http_contract_and_bound(client, auth_headers):
    brand_id, [stock_id], _ = _seed_stock(1)

    response = client.get(
        "/api/finished-goods",
        params={"status": "damaged", "brand_id": brand_id, "page": 1, "page_size": 50},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == [stock_id]
    assert {key: page[key] for key in ("page", "page_size", "has_more")} == {
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }
    assert client.get(
        "/api/finished-goods?page_size=501",
        headers=auth_headers,
    ).status_code == 422


def test_branded_stock_page_http_contract_and_search(client, auth_headers):
    _brand_id, stock_ids, model_codes = _seed_stock(2, status="available")

    response = client.get(
        "/api/finished-goods/branded-stock",
        params={"page": 1, "page_size": 50, "q": model_codes[0]},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == [stock_ids[0]]
    assert {key: page[key] for key in ("page", "page_size", "has_more")} == {
        "page": 1,
        "page_size": 50,
        "has_more": False,
    }
