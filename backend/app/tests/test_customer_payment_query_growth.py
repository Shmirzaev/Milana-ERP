from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.partners import _find_payable_invoice, get_customer_payments
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


def test_customer_payment_history_projects_only_response_columns():
    marker = uuid4().hex
    with SessionLocal() as db:
        customer = Customer(name=f"Projection {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"PAY-PROJECTION-{marker}",
            customer_id=customer.id,
            total_amount=125,
            notes="unused order note" * 20,
            printing_attachments=[{"unused": "attachment"}],
        )
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"PAY-PROJECTION-INV-{marker}",
            amount=125,
        )
        db.add(invoice)
        db.flush()
        payment = Payment(
            invoice_id=invoice.id,
            customer_id=customer.id,
            amount=40,
            payment_method="cash",
            notes="payment note",
        )
        db.add(payment)
        db.commit()
        expected = {
            "id": payment.id,
            "row_key": f"payment-{payment.id}",
            "amount": 40.0,
            "payment_method": "cash",
            "paid_at": payment.paid_at,
            "notes": "payment note",
            "order_id": order.id,
            "order_no": order.order_no,
            "invoice_id": invoice.id,
            "invoice_no": invoice.invoice_no,
            "invoice_amount": 125.0,
            "is_advance": False,
        }

        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(db.get_bind(), "before_cursor_execute", capture)
        try:
            result = get_customer_payments(customer.id, db, None)
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", capture)

    assert result == [expected]
    payment_query = next(sql for sql in statements if "from payments" in sql and "join invoices" in sql)
    selected_columns = payment_query.split(" from payments", 1)[0]
    assert "sales_orders.notes" not in selected_columns
    assert "sales_orders.printing_attachments" not in selected_columns
    assert "payments.notes" in selected_columns
    assert "invoices.invoice_no" in selected_columns
