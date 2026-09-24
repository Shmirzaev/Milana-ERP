"""Keep sales-order list totals within the existing NUMERIC(14, 2) column."""

from decimal import Decimal

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Model, SalesOrder, SalesOrderItem


MAX_ITEM_PRICE = "9999999999.99"
MAX_ORDER_TOTAL = Decimal("999999999999.99")


def _standard_model_id() -> int:
    with SessionLocal() as db:
        return db.query(Model.id).filter(Model.catalog_scope == "standard").order_by(Model.id).scalar()


def _line(model_id: int, *, quantity: int, unit_price: str) -> dict:
    return {
        "model_id": model_id,
        "color": "blue",
        "size": "M",
        "quantity": quantity,
        "unit_price": unit_price,
    }


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        )


@pytest.mark.parametrize("items", [
    lambda model_id: [_line(model_id, quantity=101, unit_price=MAX_ITEM_PRICE)],
    lambda model_id: [
        _line(model_id, quantity=100, unit_price=MAX_ITEM_PRICE),
        _line(model_id, quantity=1, unit_price="1.00"),
    ],
])
def test_create_sales_order_rejects_unrepresentable_total_without_writes(client, auth_headers, items):
    model_id = _standard_model_id()
    before = _write_counts()

    response = client.post("/api/sales-orders", headers=auth_headers, json={"items": items(model_id)})

    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "Order total exceeds the supported maximum of 999999999999.99",
    }
    assert _write_counts() == before


@pytest.mark.parametrize("last_price", ["0.99"])
def test_create_sales_order_preserves_representable_boundary_values(client, auth_headers, last_price):
    model_id = _standard_model_id()
    response = client.post("/api/sales-orders", headers=auth_headers, json={"items": [
        _line(model_id, quantity=100, unit_price=MAX_ITEM_PRICE),
        _line(model_id, quantity=1, unit_price=last_price),
    ]})

    assert response.status_code == 201, response.text
    order_id = response.json()["id"]
    with SessionLocal() as db:
        stored = db.get(SalesOrder, order_id)
        assert stored.total_amount == MAX_ORDER_TOTAL
        assert db.query(SalesOrderItem).filter_by(sales_order_id=order_id).count() == 2


def test_create_sales_order_preserves_normal_payload_and_response(client, auth_headers):
    model_id = _standard_model_id()
    response = client.post("/api/sales-orders", headers=auth_headers, json={"items": [
        _line(model_id, quantity=4, unit_price="1.25"),
        _line(model_id, quantity=2, unit_price="2.50"),
    ]})

    assert response.status_code == 201, response.text
    assert response.json()["total_amount"] == 10.0
    assert [row["quantity"] for row in response.json()["items"]] == [4, 2]


def test_create_sales_order_total_bound_preserves_authentication(client):
    model_id = _standard_model_id()
    before = _write_counts()

    response = client.post("/api/sales-orders", json={"items": [
        _line(model_id, quantity=101, unit_price=MAX_ITEM_PRICE),
    ]})

    assert response.status_code == 401
    assert _write_counts() == before
