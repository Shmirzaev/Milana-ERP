from uuid import uuid4

import pytest
from sqlalchemy import event

from app.models import Customer, Invoice, Payment, SalesOrder
from app.schemas.integrations import OneCSyncIn
from app.services.finance_1c import sync_from_1c
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("count", [1, 50, 401])
def test_1c_sync_reuses_locked_identity_rows(count):
    marker = uuid4().hex[:12]
    with TestSessionLocal() as db:
        customer = Customer(name=f"1C identity growth {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"SYNC-GROWTH-{marker}", customer_id=customer.id, total_amount=count * 100)
        db.add(order)
        db.flush()
        invoices = [
            Invoice(
                sales_order_id=order.id,
                invoice_no=f"SYNC-GROWTH-{marker}-{index}",
                amount=100,
                status="unpaid",
                external_source="1c",
                external_id=f"sync-invoice-{marker}-{index}",
            )
            for index in range(count)
        ]
        db.add_all(invoices)
        db.flush()
        payments = [
            Payment(
                invoice_id=invoice.id,
                amount=10,
                external_source="1c",
                external_id=f"sync-payment-{marker}-{index}",
            )
            for index, invoice in enumerate(invoices)
        ]
        db.add_all(payments)
        db.commit()

        payload = OneCSyncIn(
            invoices=[
                {
                    "external_id": invoice.external_id,
                    "sales_order_id": order.id,
                    "invoice_no": invoice.invoice_no,
                    "amount": 100,
                }
                for invoice in invoices
            ],
            payments=[
                {
                    "external_id": payment.external_id,
                    "invoice_external_id": invoice.external_id,
                    "amount": 50,
                }
                for payment, invoice in zip(payments, invoices)
            ],
        )
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            summary = sync_from_1c(db, payload)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert summary == {
            "invoices_created": 0,
            "invoices_updated": count,
            "payments_created": 0,
            "payments_updated": count,
            "errors": [],
        }
        db.commit()

    invoice_identity_reads = [
        statement for statement in statements
        if " from invoices " in statement and "sum(" not in statement
    ]
    payment_identity_reads = [
        statement for statement in statements
        if " from payments " in statement and "sum(" not in statement
    ]
    assert len(invoice_identity_reads) <= 2
    assert len(payment_identity_reads) == 1
    assert len(statements) <= 10
