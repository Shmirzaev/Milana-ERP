"""Cent-sized advances must be saved, not dropped or dereferenced as None."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def cent_customer():
    with TestSessionLocal() as db:
        customer = Customer(name="Synthetic cent payments")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"CENT-{uuid4().hex}", customer_id=customer.id, total_amount=1)
        db.add(order)
        db.flush()
        invoice = Invoice(invoice_no=f"CENT-{uuid4().hex}", sales_order_id=order.id, amount=1, status="unpaid")
        db.add(invoice)
        db.commit()
        return customer.id, order.id, invoice.id


def _state(cid):
    with TestSessionLocal() as db:
        rows = db.query(Payment).filter_by(customer_id=cid).all()
        return ([(row.id, row.invoice_id, row.amount) for row in rows],
                db.query(AuditLog).count(), db.query(IdempotencyRecord).count())


@pytest.mark.parametrize(("mode", "amount", "invoice_paid", "advance"), [
    ("advance", 0.01, "0", "0.01"),
    ("advance", 0.02, "0", "0.02"),
    ("advance", 0.29, "0", "0.29"),
    ("advance", 0.07, "0", "0.07"),
    ("advance", 0.30, "0", "0.30"),
    ("invoice", 0.01, "0.01", "0"),
    ("invoice", 1.01, "1", "0.01"),
    ("paid_invoice", 0.01, "1", "0.01"),
])
def test_cent_payment_and_retry_preserve_full_amount(client, auth_headers, cent_customer, mode, amount, invoice_paid, advance):
    cid, oid, iid = cent_customer
    if mode == "paid_invoice":
        with TestSessionLocal() as db:
            db.add(Payment(invoice_id=iid, customer_id=cid, amount=1))
            db.get(Invoice, iid).status = "paid"
            db.commit()
    payload = {"amount": amount, "payment_method": "cash"}
    if mode != "advance":
        payload["sales_order_id"] = oid
    headers = {**auth_headers, "Idempotency-Key": f"cent-{uuid4().hex}"}
    response = client.post(f"/api/customers/{cid}/payments", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["id"]
    before = _state(cid)
    retry = client.post(f"/api/customers/{cid}/payments", headers=headers, json=payload)
    assert retry.status_code == 201 and retry.json() == response.json()
    assert _state(cid) == before
    with TestSessionLocal() as db:
        payments = db.query(Payment).filter_by(customer_id=cid).all()
        assert sum((p.amount for p in payments if p.invoice_id == iid), Decimal(0)) == Decimal(invoice_paid)
        assert sum((p.amount for p in payments if p.invoice_id is None), Decimal(0)) == Decimal(advance)


@pytest.mark.parametrize("amount", [0, -1, 0.001, 0.015, "NaN", "Infinity", "-Infinity"])
def test_invalid_minor_units_are_rejected_before_writes(client, auth_headers, cent_customer, amount):
    cid, _, _ = cent_customer
    before = _state(cid)
    response = client.post(f"/api/customers/{cid}/payments", headers=auth_headers, json={"amount": amount})
    assert response.status_code == 422, response.text
    assert _state(cid) == before


def test_customer_can_settle_exact_one_cent_invoice_balance(client, auth_headers, cent_customer):
    cid, oid, iid = cent_customer

    first = client.post(
        f"/api/customers/{cid}/payments",
        headers=auth_headers,
        json={"sales_order_id": oid, "amount": "0.99", "payment_method": "cash"},
    )
    second = client.post(
        f"/api/customers/{cid}/payments",
        headers=auth_headers,
        json={"sales_order_id": oid, "amount": "0.01", "payment_method": "cash"},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["invoice_id"] == second.json()["invoice_id"] == iid
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, iid)
        payments = db.query(Payment).filter_by(customer_id=cid).all()
        assert invoice.status == "paid"
        assert sum((row.amount for row in payments if row.invoice_id == iid), Decimal(0)) == Decimal("1.00")
        assert not any(row.invoice_id is None for row in payments)
