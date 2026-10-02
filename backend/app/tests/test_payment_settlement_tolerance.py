"""Approved USD settlement is a status rule, never an invented receipt."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import Customer, Invoice, Payment, SalesOrder
from app.services.payments import invoice_paid_total, invoice_payment_status, refresh_invoice_status
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def settlement_order():
    with TestSessionLocal() as db:
        customer = Customer(name="Synthetic USD settlement")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"SETTLE-{uuid4().hex}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(invoice_no=f"SETTLE-{uuid4().hex}", sales_order_id=order.id, amount=100, status="unpaid")
        db.add(invoice)
        db.commit()
        return customer.id, order.id, invoice.id


@pytest.mark.parametrize("route", ["customer", "finance"])
@pytest.mark.parametrize(("shortfall", "status", "order_status"), [
    ("0.99", "paid", "paid"),
    ("1.00", "paid", "paid"),
    ("1.01", "partially_paid", "partial"),
])
def test_settlement_boundary_retains_actual_debt_and_retry(
    client, auth_headers, settlement_order, route, shortfall, status, order_status,
):
    cid, oid, iid = settlement_order
    paid = Decimal("100") - Decimal(shortfall)
    if route == "customer":
        url = f"/api/customers/{cid}/payments"
        payload = {"sales_order_id": oid, "amount": float(paid)}
    else:
        url = "/api/finance/payments"
        payload = {"invoice_id": iid, "amount": float(paid)}
    headers = {**auth_headers, "Idempotency-Key": f"settle-{uuid4().hex}"}
    response = client.post(url, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    retry = client.post(url, headers=headers, json=payload)
    assert retry.status_code == 201 and retry.json() == response.json()

    with TestSessionLocal() as db:
        assert invoice_paid_total(db, iid) == paid
        assert db.get(Invoice, iid).status == status
        assert db.get(Invoice, iid).amount == Decimal("100")
        assert db.query(Payment).filter_by(customer_id=cid).count() == 1

    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    assert history.status_code == 200, history.text
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["payment_status"] == order_status
    assert row["paid_total"] == float(paid)
    assert row["balance_due"] == float(Decimal(shortfall))
    assert row["invoices"][0]["status"] == status
    assert row["invoices"][0]["raw_paid_amount"] == float(paid)


def test_exact_cent_on_settled_invoice_is_allocated_before_advance(client, auth_headers, settlement_order):
    cid, oid, iid = settlement_order
    with TestSessionLocal() as db:
        db.add(Payment(invoice_id=iid, customer_id=cid, amount=Decimal("99.99")))
        refresh_invoice_status(db, db.get(Invoice, iid))
        db.commit()
    response = client.post(f"/api/customers/{cid}/payments", headers=auth_headers,
                           json={"sales_order_id": oid, "amount": 0.02})
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        rows = db.query(Payment).filter_by(customer_id=cid).all()
        assert sum((p.amount for p in rows if p.invoice_id == iid), Decimal(0)) == Decimal("100.00")
        assert sum((p.amount for p in rows if p.invoice_id is None), Decimal(0)) == Decimal("0.01")


def test_cent_partial_payment_has_partial_status(client, auth_headers, settlement_order):
    cid, oid, iid = settlement_order
    response = client.post(f"/api/customers/{cid}/payments", headers=auth_headers,
                           json={"sales_order_id": oid, "amount": 0.01})
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        assert db.get(Invoice, iid).status == "partially_paid"
        assert invoice_paid_total(db, iid) == Decimal("0.01")
    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["payment_status"] == "partial" and row["balance_due"] == 99.99


@pytest.mark.parametrize("status", ["void", "cancelled"])
def test_reversed_invoice_is_never_settled_or_paid(client, auth_headers, settlement_order, status):
    cid, oid, iid = settlement_order
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, iid)
        invoice.amount = Decimal("0.99")
        invoice.status = status
        refresh_invoice_status(db, invoice)
        assert invoice.status == status
        db.commit()
    rejected = client.post("/api/finance/payments", headers=auth_headers, json={"invoice_id": iid, "amount": 0.01})
    assert rejected.status_code == 409, rejected.text
    advance = client.post(f"/api/customers/{cid}/payments", headers=auth_headers,
                          json={"sales_order_id": oid, "amount": 0.01})
    assert advance.status_code == 201 and advance.json()["is_advance"] is True
    with TestSessionLocal() as db:
        assert db.get(Invoice, iid).status == status
        assert invoice_paid_total(db, iid) == 0
    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["payment_status"] == status
    assert row["invoice_total"] == row["paid_total"] == row["balance_due"] == 0
    assert row["invoices"][0]["status"] == status


def test_cancelled_invoice_is_excluded_from_active_order_status(client, auth_headers, settlement_order):
    cid, oid, iid = settlement_order
    with TestSessionLocal() as db:
        db.get(Invoice, iid).status = "cancelled"
        active = Invoice(invoice_no=f"ACTIVE-{uuid4().hex}", sales_order_id=oid, amount=100, status="unpaid")
        db.add(active)
        db.commit()
    response = client.post(f"/api/customers/{cid}/payments", headers=auth_headers,
                           json={"sales_order_id": oid, "amount": 99})
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        assert invoice_paid_total(db, iid) == 0
    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["payment_status"] == "paid"
    assert row["invoice_total"] == 100 and row["paid_total"] == 99 and row["balance_due"] == 1


def test_read_status_applies_small_unpaid_settlement_without_creating_receipts(client, auth_headers, settlement_order):
    cid, oid, iid = settlement_order
    with TestSessionLocal() as db:
        db.get(Invoice, iid).amount = Decimal("1.00")
        db.commit()
    history = client.get(f"/api/customers/{cid}/orders", headers=auth_headers)
    row = next(row for row in history.json() if row["id"] == oid)
    assert row["payment_status"] == row["invoices"][0]["status"] == "paid"
    assert row["balance_due"] == 1 and row["paid_total"] == 0
    with TestSessionLocal() as db:
        assert db.query(Payment).filter_by(customer_id=cid).count() == 0
        assert db.get(Invoice, iid).status == "unpaid", "A history GET must not mutate historical rows"


def test_status_uses_decimal_boundaries_for_large_ledger_amounts():
    # Numeric(14,2) values must not lose a cent when converted to binary float.
    assert invoice_payment_status(Decimal("999999999999.99"), Decimal("999999999998.99")) == "paid"
    assert invoice_payment_status(Decimal("999999999999.99"), Decimal("999999999998.98")) == "partially_paid"


@pytest.mark.parametrize(("amount", "status"), [("0.99", "paid"), ("1.00", "paid"), ("1.01", "unpaid")])
def test_no_receipt_status_respects_literal_small_balance_rule(amount, status):
    assert invoice_payment_status(Decimal(amount), Decimal(0)) == status
