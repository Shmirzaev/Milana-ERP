"""Order APIs must not publish money without its currency provenance."""

from decimal import Decimal
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Model, SalesOrder, SalesOrderItem


_PLANNING_MONEY_FIELDS = (
    "planning_estimated_material_cost",
    "planning_estimated_labor_cost",
    "planning_estimated_electricity_cost",
    "planning_estimated_other_cost",
    "planning_estimated_net_cost",
    "planning_suggested_price_15",
    "planning_suggested_price_20",
)


def _seed_sales_order(currency: str | None) -> int:
    with SessionLocal() as db:
        model_id = db.query(Model.id).filter(Model.catalog_scope == "standard").order_by(Model.id).scalar()
        order = SalesOrder(
            order_no=f"FN08-{uuid4().hex[:12]}",
            order_type="client_order",
            status="confirmed",
            total_amount=Decimal("125.00"),
            currency=currency,
            planning_estimated_material_cost=Decimal("40.00"),
            planning_estimated_labor_cost=Decimal("10.00"),
            planning_estimated_electricity_cost=Decimal("2.00"),
            planning_estimated_other_cost=Decimal("3.00"),
            planning_estimated_net_cost=Decimal("55.00"),
            planning_suggested_price_15=Decimal("63.25"),
            planning_suggested_price_20=Decimal("66.00"),
            planning_estimated_lead_time_minutes=80,
            planning_estimate_comment="Keep this non-monetary planning note",
        )
        db.add(order)
        db.flush()
        db.add(SalesOrderItem(
            sales_order_id=order.id,
            model_id=model_id,
            color="blue",
            size="M",
            quantity=2,
            unit_price=Decimal("62.50"),
        ))
        db.commit()
        return int(order.id)


def test_sales_order_responses_redact_unprovenanced_estimates_and_currencyless_revenue(client, auth_headers):
    order_id = _seed_sales_order(None)

    detail = client.get(f"/api/sales-orders/{order_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["currency"] is None
    assert payload["total_amount"] is None
    assert payload["items"][0]["unit_price"] is None
    assert all(payload[field] is None for field in _PLANNING_MONEY_FIELDS)
    assert payload["planning_estimated_lead_time_minutes"] == 80
    assert payload["planning_estimate_comment"] == "Keep this non-monetary planning note"

    context = client.get(f"/api/sales-orders/{order_id}/page-context", headers=auth_headers)
    assert context.status_code == 200, context.text
    assert context.json()["sales_order"]["total_amount"] is None
    assert context.json()["sales_order"]["planning_estimated_material_cost"] is None

    listing = client.get("/api/sales-orders", params={"q": f"FN08-"}, headers=auth_headers)
    assert listing.status_code == 200, listing.text
    listed = next(row for row in listing.json() if row["id"] == order_id)
    assert listed["currency"] is None
    assert listed["total_amount"] is None
    assert all(listed[field] is None for field in _PLANNING_MONEY_FIELDS)


def test_sales_order_revenue_keeps_its_known_currency_but_estimates_stay_unavailable(client, auth_headers):
    order_id = _seed_sales_order("UZS")

    response = client.get(f"/api/sales-orders/{order_id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total_amount"] == 125.0
    assert payload["currency"] == "UZS"
    assert payload["items"][0]["unit_price"] == 62.5
    assert all(payload[field] is None for field in _PLANNING_MONEY_FIELDS)
