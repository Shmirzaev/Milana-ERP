from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import Customer, Invoice, SalesOrder


def _create_invoice(session_factory, amount=100):
    with session_factory() as db:
        customer = Customer(name=f"Revenue dates {uuid4().hex}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"REV-{uuid4().hex}", customer_id=customer.id, total_amount=amount)
        db.add(order)
        db.flush()
        invoice = Invoice(sales_order_id=order.id, invoice_no=f"REV-{uuid4().hex}", amount=amount, status="unpaid")
        db.add(invoice)
        db.commit()
        return customer.id, order.id, invoice.id


@pytest.mark.parametrize("date_from,date_to", [
    ("2089-02-03T00:00:00Z", "2089-02-03T00:00:00Z"),
    ("2089-02-03T05:00:00+05:00", "2089-02-03T05:00:00+05:00"),
    ("2089-02-03T00:00:00", "2089-02-03T00:00:00"),
])
def test_revenue_date_bounds_accept_equivalent_utc_instants(client, auth_headers, date_from, date_to):
    _, _, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        invoice.issued_at = datetime(2089, 2, 3, tzinfo=timezone.utc)
        invoice.amount = 123.45
        db.commit()
    response = client.get("/api/finance/revenue-by-period", headers=auth_headers,
                          params={"from": date_from, "to": date_to})
    assert response.status_code == 200, response.text
    assert response.json() == [{"period": "2089-02", "amount": 123.45}]


def test_revenue_date_bounds_use_created_date_fallback_and_exclude_outside(client, auth_headers):
    _, _, invoice_id = _create_invoice(SessionLocal)
    with SessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        invoice.issued_at = None
        invoice.created_at = datetime(2089, 2, 3, tzinfo=timezone.utc)
        invoice.amount = 50
        db.commit()
    selected = client.get("/api/finance/revenue-by-period", headers=auth_headers,
                          params={"from": "2089-02-01T00:00:00Z", "to": "2089-02-28T00:00:00Z"})
    assert selected.status_code == 200, selected.text
    assert selected.json() == [{"period": "2089-02", "amount": 50.0}]
    excluded = client.get("/api/finance/revenue-by-period", headers=auth_headers,
                          params={"from": "2089-03-01T00:00:00Z"})
    assert excluded.status_code == 200, excluded.text
    assert excluded.json() == []
