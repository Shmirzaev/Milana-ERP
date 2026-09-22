from datetime import datetime, timezone

import pytest

from app.db.session import SessionLocal
from app.models import Invoice
from app.tests.test_payment_integrity import _create_invoice


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


def test_revenue_by_period_aggregates_in_sql_without_loading_invoice_rows(client, auth_headers):
    invoices = []
    for amount, issued_at in (
        (10, datetime(2089, 4, 1, tzinfo=timezone.utc)),
        (12.34, datetime(2089, 4, 30, tzinfo=timezone.utc)),
        (99, datetime(2089, 5, 1, tzinfo=timezone.utc)),
    ):
        _, _, invoice_id = _create_invoice(SessionLocal)
        invoices.append(invoice_id)
        with SessionLocal() as db:
            invoice = db.get(Invoice, invoice_id)
            invoice.issued_at = issued_at
            invoice.amount = amount
            db.commit()

    response = client.get(
        "/api/finance/revenue-by-period",
        headers=auth_headers,
        params={"from": "2089-04-01T00:00:00Z", "to": "2089-05-31T23:59:59Z"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == [
        {"period": "2089-04", "amount": 22.34},
        {"period": "2089-05", "amount": 99.0},
    ]
