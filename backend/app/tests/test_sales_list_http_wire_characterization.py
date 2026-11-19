"""Characterize the existing list route's HTTP encoding; no database claim.

The service normally constructs SalesOrderListRow and returns model_dump() dicts.
Supplying that same shape here isolates FastAPI's response encoding, including
UTC offset spelling which a response_model change could alter.
"""
from datetime import datetime, timezone

import pytest
from fastapi.encoders import jsonable_encoder

from app.libs.dto.sales.sales_order_output import SalesOrderListRow
from app.models.sales import orders_service


@pytest.mark.parametrize("include_total", [False, True])
def test_sales_list_http_preserves_list_or_page_and_utc_spelling(
    client, auth_headers, monkeypatch, include_total
):
    timestamp = datetime(2026, 2, 3, 4, 5, 6, 123456, tzinfo=timezone.utc)
    row = SalesOrderListRow(
        id=123,
        order_no="WIRE-SALES-123",
        customer_id=None,
        customer_name=None,
        order_type="client_order",
        status="draft",
        deadline=None,
        total_amount=12.5,
        planning_estimate_submitted_at=timestamp,
        customer=None,
        created_at=timestamp,
        total_quantity=0,
    ).model_dump()
    payload = (
        {"rows": [row], "total": 1, "page": 1, "page_size": 50}
        if include_total
        else [row]
    )
    seen = []

    def list_orders(_db, **kwargs):
        seen.append(kwargs["include_total"])
        return payload

    monkeypatch.setattr(orders_service, "list_sales_orders", list_orders)
    response = client.get(
        "/api/sales-orders",
        params={"include_total": str(include_total).lower()},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert seen == [include_total]
    body = response.json()
    assert body == jsonable_encoder(payload)
    actual_row = body["rows"][0] if include_total else body[0]
    assert actual_row["created_at"] == "2026-02-03T04:05:06.123456+00:00"
    assert actual_row["planning_estimate_submitted_at"] == "2026-02-03T04:05:06.123456+00:00"
    assert actual_row["deadline"] is None
    assert actual_row["customer"] is None
    assert actual_row["total_amount"] == 12.5
    assert actual_row["total_quantity"] == 0
