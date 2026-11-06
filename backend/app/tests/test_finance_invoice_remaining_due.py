"""The Finance payment form defaults to actual due, never the original total."""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models.finance_service import invoice_list_page
from app.schemas import Customer, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal


def seed_invoice(db, prefix, *, paid=(), amount="200"):
    customer = Customer(name=prefix)
    db.add(customer)
    db.flush()
    order = SalesOrder(order_no=prefix, customer_id=customer.id, status="confirmed", total_amount=Decimal(amount))
    db.add(order)
    db.flush()
    invoice = Invoice(invoice_no=prefix, sales_order_id=order.id, amount=Decimal(amount), status="unpaid")
    db.add(invoice)
    db.flush()
    for value in paid:
        db.add(Payment(invoice_id=invoice.id, customer_id=customer.id, amount=Decimal(value)))
    db.flush()
    return invoice, customer


@pytest.mark.parametrize("payments,expected_due,expected_status", [
    ([], 200, "unpaid"),
    (["10", "15"], 175, "partially_paid"),
    (["25", "175"], 0, "paid"),
    (["25", "200"], 0, "paid"),
    # The existing display tolerance does not erase an actual monetary balance.
    (["199"], 1, "paid"),
    (["199.99"], 0.01, "paid"),
])
def test_invoice_http_projection_uses_receipts_without_changing_amount_or_status_policy(
    client, auth_headers, payments, expected_due, expected_status,
):
    prefix = "DUE-" + uuid4().hex
    with TestSessionLocal() as db:
        invoice, _ = seed_invoice(db, prefix, paid=payments)
        db.commit()
        invoice_id = invoice.id
    response = client.get("/api/finance/invoices", params={"search": prefix}, headers=auth_headers)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1 and len(page["items"]) == 1
    row = page["items"][0]
    assert (row["id"], row["amount"], row["balance_due"], row["status"]) == (
        invoice_id, 200, expected_due, expected_status,
    )
    with TestSessionLocal() as db:
        # GET is a projection: it does not repair persisted status or receipts.
        assert db.get(Invoice, invoice_id).status == "unpaid"
        assert [p.amount for p in db.query(Payment).filter_by(invoice_id=invoice_id).order_by(Payment.id)] == [Decimal(v) for v in payments]


def test_due_is_grouped_per_invoice_and_survives_search_and_pagination(client, auth_headers):
    prefix = "DUE-PAGES-" + uuid4().hex
    with TestSessionLocal() as db:
        expected = {}
        for index, payments in enumerate([[], ["10", "15"], ["200"], ["225"]]):
            invoice, customer = seed_invoice(db, f"{prefix}-{index}", paid=payments)
            expected[invoice.id] = max(Decimal("200") - sum((Decimal(v) for v in payments), Decimal(0)), Decimal(0))
            # Unallocated customer advances are not invoice receipts.
            db.add(Payment(customer_id=customer.id, amount=Decimal("900")))
        other, _ = seed_invoice(db, "OTHER-" + uuid4().hex, paid=["195"])
        db.commit()
    seen = {}
    for offset in [0, 2]:
        response = client.get("/api/finance/invoices", params={"search": prefix, "limit": 2, "offset": offset}, headers=auth_headers)
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 4 and page["limit"] == 2 and page["offset"] == offset
        assert len(page["items"]) == 2
        for row in page["items"]:
            assert row["id"] not in seen and row["id"] != other.id
            seen[row["id"]] = Decimal(str(row["balance_due"]))
    assert seen == expected


def test_due_projection_does_not_flush_commit_or_mutate_pending_objects(monkeypatch):
    prefix = "DUE-READONLY-" + uuid4().hex
    with TestSessionLocal() as db:
        invoice, _ = seed_invoice(db, prefix, paid=["25"])
        db.commit()
        invoice_id = invoice.id
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        pending = Customer(name="Pending unrelated customer")
        db.add(pending)
        statements = []
        def observe(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())
        def unexpected(*args, **kwargs):
            raise AssertionError("Read projection must not flush or commit")
        monkeypatch.setattr(db, "flush", unexpected)
        monkeypatch.setattr(db, "commit", unexpected)
        event.listen(db.bind, "before_cursor_execute", observe)
        try:
            page = invoice_list_page(db, search=prefix)
        finally:
            event.remove(db.bind, "before_cursor_execute", observe)
        assert page["items"][0]["balance_due"] == 175
        assert pending.id is None and pending in db.new
        assert invoice.status == "unpaid" and not db.is_modified(invoice)
        assert statements and set(statements) == {"SELECT"}
        db.rollback()


def test_finance_due_projection_keeps_authentication_requirement(client):
    assert client.get("/api/finance/invoices").status_code == 401
