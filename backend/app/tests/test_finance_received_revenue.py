"""Cash sale revenue uses real receipts; unpaid debt and advances stay distinct."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.dt import as_utc
from app.db.session import SessionLocal
from app.models import Customer, Invoice, Payment, SalesOrder, Shipment
from app.services.finance import list_recent_invoices, order_profit, revenue_by_period, revenue_total


def _order(db, *, amount="100", status="ready_to_ship"):
    customer = Customer(name=f"Receipt revenue {uuid4().hex}")
    db.add(customer)
    db.flush()
    order = SalesOrder(order_no=f"CASH-{uuid4().hex}", customer_id=customer.id,
                       total_amount=Decimal(amount), status=status)
    db.add(order)
    db.flush()
    return order


def _invoice(db, order, *, amount="100", status="unpaid"):
    invoice = Invoice(invoice_no=f"CASH-{uuid4().hex}", sales_order_id=order.id,
                      amount=Decimal(amount), status=status,
                      issued_at=datetime(2089, 1, 1, tzinfo=timezone.utc))
    db.add(invoice)
    db.flush()
    return invoice


def _pay(db, invoice, amount, month, *, customer_id=None):
    payment = Payment(invoice_id=invoice.id if invoice else None,
                      customer_id=customer_id, amount=Decimal(amount),
                      paid_at=datetime(2090, month, 10, tzinfo=timezone.utc))
    db.add(payment)
    db.flush()
    return payment


def _periods(db, **kwargs):
    return revenue_by_period(db, from_dt=datetime(2090, 1, 1, tzinfo=timezone.utc), **kwargs)


def test_partial_cash_receipts_drive_total_trend_and_order_profit(client, auth_headers):
    before = client.get("/api/finance/dashboard", headers=auth_headers).json()
    with SessionLocal() as db:
        order = _order(db)
        invoice = _invoice(db, order)
        _pay(db, invoice, "30", 1)
        # Historical persisted status need not already match current tolerance.
        _pay(db, invoice, "69", 2)
        _pay(db, None, "40", 2, customer_id=order.customer_id)
        db.commit()
        assert order_profit(db, order.id)["revenue"] == 99
        assert order_profit(db, order.id)["gross_profit"] == 99
        assert _periods(db) == [{"period": "2090-01", "amount": 30},
                               {"period": "2090-02", "amount": 69}]
        recent = next(row for row in list_recent_invoices(db) if row["id"] == invoice.id)
        assert recent["status"] == "paid"
        assert db.get(Invoice, invoice.id).status == "unpaid"

    finance = client.get("/api/finance/dashboard", headers=auth_headers)
    dashboard = client.get("/api/dashboard/finance", headers=auth_headers)
    assert finance.status_code == dashboard.status_code == 200
    assert finance.json() == dashboard.json()
    assert finance.json()["revenue_total"] == before["revenue_total"] + 99
    assert finance.json()["payments_received"] == before["payments_received"] + 139


def test_historical_overpayments_are_allocated_before_report_date_filter(client, auth_headers):
    with SessionLocal() as db:
        order = _order(db)
        invoice = _invoice(db, order)
        # Arrival order differs from effective receipt chronology.
        _pay(db, invoice, "10", 3)
        legacy = _pay(db, invoice, "70", 1)
        legacy.external_source = "1c"
        legacy.external_id = f"historic-{uuid4().hex}"
        _pay(db, invoice, "60", 2)
        db.commit()
        assert order_profit(db, order.id)["revenue"] == 100
        assert _periods(db) == [{"period": "2090-01", "amount": 70},
                               {"period": "2090-02", "amount": 30}]
    response = client.get("/api/finance/revenue-by-period", headers=auth_headers,
                          params={"from": "2090-02-01T00:00:00Z", "to": "2090-03-31T23:59:59Z"})
    assert response.status_code == 200, response.text
    assert response.json() == [{"period": "2090-02", "amount": 30}]


@pytest.mark.parametrize("invoice_status,order_status", [
    ("void", "shipped"), ("cancelled", "shipped"), ("paid", "cancelled"),
])
def test_reversed_sale_excludes_cash_revenue_without_deleting_receipts(invoice_status, order_status):
    with SessionLocal() as db:
        before = revenue_total(db)
        order = _order(db, status=order_status)
        invoice = _invoice(db, order, status=invoice_status)
        _pay(db, invoice, "100", 1)
        db.commit()
        assert revenue_total(db) == before
        assert _periods(db) == []
        assert order_profit(db, order.id)["revenue"] == 0
        assert db.query(Payment).filter_by(invoice_id=invoice.id).count() == 1
        if invoice_status in {"void", "cancelled"}:
            row = next(row for row in list_recent_invoices(db) if row["id"] == invoice.id)
            assert row["status"] == invoice_status


def test_unpaid_and_externally_marked_paid_invoices_do_not_invent_cash_revenue():
    with SessionLocal() as db:
        before = revenue_total(db)
        order = _order(db)
        _invoice(db, order, status="paid")
        _invoice(db, order, status="unpaid")
        _pay(db, None, "50", 1, customer_id=order.customer_id)
        db.commit()
        assert revenue_total(db) == before
        assert _periods(db) == []
        assert order_profit(db, order.id)["revenue"] == 0


@pytest.mark.parametrize("shipment_status,deleted,order_status,expected", [
    ("shipped", False, "ready_to_ship", "unpaid"),
    ("delivered", False, "ready_to_ship", "unpaid"),
    ("created", False, "ready_to_ship", "no_invoice"),
    ("cancelled", False, "ready_to_ship", "no_invoice"),
    ("shipped", True, "ready_to_ship", "no_invoice"),
    (None, False, "shipped", "no_invoice"),
    ("shipped", False, "cancelled", "cancelled"),
])
def test_shipped_no_invoice_order_exposes_actual_unpaid_debt(
    client, auth_headers, shipment_status, deleted, order_status, expected,
):
    with SessionLocal() as db:
        # Never-paid $1 debt is still real unpaid shipment debt.
        order = _order(db, amount="1", status=order_status)
        if shipment_status:
            db.add(Shipment(shipment_no=f"CASH-{uuid4().hex}", sales_order_id=order.id,
                            customer_id=order.customer_id, status=shipment_status,
                            deleted_at=datetime.now(timezone.utc) if deleted else None))
        db.commit()
        order_id, customer_id = order.id, order.customer_id
    response = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == order_id)
    assert row["payment_status"] == expected
    assert row["balance_due"] == 1
    assert row["paid_total"] == 0
    assert row["invoice_total"] == 0
    with SessionLocal() as db:
        assert db.get(SalesOrder, order_id).status == order_status
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 0
        assert order_profit(db, order_id)["revenue"] == 0


def test_fractional_payments_and_utc_boundary_are_bucketed_exactly():
    with SessionLocal() as db:
        order = _order(db, amount="1.30")
        invoice = _invoice(db, order, amount="1.30")
        db.add_all([
            Payment(invoice_id=invoice.id, amount=Decimal("0.70"),
                    paid_at=datetime(2090, 2, 28, 23, 59, tzinfo=timezone.utc)),
            Payment(invoice_id=invoice.id, amount=Decimal("0.60"),
                    paid_at=datetime(2090, 3, 1, tzinfo=timezone.utc)),
        ])
        db.commit()
        assert _periods(db) == [{"period": "2090-02", "amount": 0.7},
                               {"period": "2090-03", "amount": 0.6}]
        assert order_profit(db, order.id)["revenue"] == 1.3


@pytest.mark.parametrize("is_advance", [False, True])
def test_payment_writer_preserves_offset_instant_and_utc_revenue_month(client, auth_headers, is_advance):
    with SessionLocal() as db:
        order = _order(db)
        invoice = _invoice(db, order)
        db.commit()
        customer_id, invoice_id = order.customer_id, invoice.id
    payload = {"amount": 70, "paid_at": "2090-03-01T00:00:00+05:00"}
    if is_advance:
        path = f"/api/customers/{customer_id}/payments"
    else:
        path = "/api/finance/payments"
        payload["invoice_id"] = invoice_id
    response = client.post(path, headers=auth_headers, json=payload)
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        payment = db.get(Payment, response.json()["id"])
        assert as_utc(payment.paid_at) == datetime(2090, 2, 28, 19, tzinfo=timezone.utc)
        assert _periods(db) == ([] if is_advance else [{"period": "2090-02", "amount": 70}])
