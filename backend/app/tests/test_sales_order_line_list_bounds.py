"""Keep each sales order's financially relevant item input bounded."""

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import AuditLog, SalesOrder, SalesOrderItem
from app.schemas.sales import SalesOrderIn


def _line(model_id: int) -> dict:
    return {
        "model_id": model_id,
        "color": "blue",
        "size": "M",
        "quantity": 1,
        "unit_price": "0.01",
    }


def _write_counts() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return (
            db.query(SalesOrder).count(),
            db.query(SalesOrderItem).count(),
            db.query(AuditLog).count(),
        )


def test_sales_order_schema_accepts_exactly_one_thousand_lines():
    parsed = SalesOrderIn(items=[_line(1)] * 1000)

    assert len(parsed.items) == 1000


def test_sales_order_schema_rejects_more_than_one_thousand_lines():
    with pytest.raises(ValidationError):
        SalesOrderIn(items=[_line(1)] * 1001)


def test_oversized_sales_order_rejected_before_writes_and_keeps_auth_precedence(client, auth_headers):
    before = _write_counts()
    payload = {"items": [_line(1)] * 1001}

    unauthorized = client.post("/api/sales-orders", json=payload)
    assert unauthorized.status_code == 401

    response = client.post("/api/sales-orders", json=payload, headers=auth_headers)
    assert response.status_code == 422, response.text
    assert _write_counts() == before
