from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.partners import _find_payable_invoice
from app.db.session import SessionLocal
from app.models import Customer, Invoice, Payment, SalesOrder


def _order(invoice_count, *, all_paid=False):
    marker = uuid4().hex
    with SessionLocal() as db:
        customer = Customer(name=f"Query test {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"PAY-Q-{marker}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoices = [Invoice(sales_order_id=order.id, invoice_no=f"PAY-Q-{marker}-{i}",
                            amount=100, status="unpaid") for i in range(invoice_count)]
        db.add_all(invoices)
        db.flush()
        for i, invoice in enumerate(invoices):
            if all_paid or i < invoice_count - 1:
                # Multiple partial payments must sum; status may be stale.
                db.add_all([Payment(invoice_id=invoice.id, customer_id=customer.id, amount=70),
                            Payment(invoice_id=invoice.id, customer_id=customer.id, amount=30)])
        db.add(Payment(customer_id=customer.id, amount=9999))  # Advance is not invoice payment.
        db.commit()
        return order.id, invoices[-1].id if invoices else None


@pytest.mark.parametrize("count,expected_queries", [(1, 2), (50, 2), (401, 3)])
def test_payable_selection_batches_payment_totals(count, expected_queries):
    order_id, last_invoice_id = _order(count)
    with SessionLocal() as db:
        order = db.get(SalesOrder, order_id)
        queries = []

        def capture(_conn, _cursor, statement, *_):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            result = _find_payable_invoice(db, order)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        assert result.id == last_invoice_id
        assert len(queries) == expected_queries


@pytest.mark.parametrize("count", [0, 3])
def test_payable_selection_has_no_candidate_for_empty_or_fully_paid_order(count):
    order_id, _ = _order(count, all_paid=True)
    with SessionLocal() as db:
        assert _find_payable_invoice(db, db.get(SalesOrder, order_id)) is None


def test_payable_selection_keeps_first_invoice_and_ignores_other_orders():
    order_id, first_id = _order(1)
    other_id, _ = _order(2, all_paid=True)
    with SessionLocal() as db:
        order = db.get(SalesOrder, order_id)
        db.add(Invoice(sales_order_id=order_id, invoice_no=f"SECOND-{uuid4().hex}", amount=100))
        db.commit()
        assert _find_payable_invoice(db, order).id == first_id
        assert _find_payable_invoice(db, db.get(SalesOrder, other_id)) is None
