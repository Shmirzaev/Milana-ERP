"""Reject values that cannot fit the existing sales-item database columns."""

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import SalesOrder, SalesOrderItem
from app.schemas.sales import SalesOrderItemIn


def _item(**overrides):
    return {"model_id": 1, "color": "blue", "size": "M", "quantity": 1, **overrides}


@pytest.mark.parametrize("overrides", [
    {"unit_price": "Infinity"},
    {"unit_price": "NaN"},
    {"unit_price": 10_000_000_000},
    {"quantity": 2_147_483_648},
    {"requested_pack_count": 2_147_483_648},
])
def test_sales_item_rejects_unrepresentable_numbers(overrides):
    with pytest.raises(ValidationError):
        SalesOrderItemIn(**_item(**overrides))


@pytest.mark.parametrize("overrides", [
    {"unit_price": None, "quantity": 0},
    {"unit_price": 0},
    {"unit_price": 9_999_999_999.99, "quantity": 2_147_483_647},
    {"quantity": None, "requested_pack_count": 2_147_483_647},
])
def test_sales_item_preserves_supported_numeric_values(overrides):
    parsed = SalesOrderItemIn(**_item(**overrides))
    for field, value in overrides.items():
        assert getattr(parsed, field) == value


@pytest.mark.parametrize("overrides", [
    {"unit_price": "Infinity"}, {"unit_price": 10_000_000_000},
    {"quantity": 2_147_483_648}, {"requested_pack_count": 2_147_483_648},
])
def test_sales_item_invalid_numbers_reject_before_order_creation(client, auth_headers, overrides):
    with SessionLocal() as db:
        before = (db.query(SalesOrder).count(), db.query(SalesOrderItem).count())
    response = client.post("/api/sales-orders", headers=auth_headers, json={"items": [_item(**overrides)]})
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert (db.query(SalesOrder).count(), db.query(SalesOrderItem).count()) == before
