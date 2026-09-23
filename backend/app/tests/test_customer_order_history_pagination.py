from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.partners import get_customer_orders
from app.db.session import SessionLocal
from app.models import Customer, Invoice, Payment, SalesOrder


def _seed_orders(count, *, status="confirmed"):
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        customer = Customer(name=f"PERF35 order customer {marker}")
        db.add(customer)
        db.flush()
        rows = [
            SalesOrder(
                order_no=f"PERF35-CO-{marker}-{number:04d}",
                customer_id=customer.id,
                status=status,
                total_amount=number + 10,
            )
            for number in range(count)
        ]
        db.add_all(rows)
        db.commit()
        return int(customer.id), [int(row.id) for row in rows]


def _read(customer_id, **kwargs):
    with SessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = get_customer_orders(customer_id, db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, statements


@pytest.mark.parametrize("count", [1, 50, 401])
def test_customer_order_pages_bound_rows_and_dependent_queries(count):
    customer_id, created_ids = _seed_orders(count)

    page, statements = _read(customer_id, page=1, page_size=count)
    legacy, _ = _read(customer_id)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == count
    assert page["has_more"] is False
    assert [row["id"] for row in page["rows"]] == list(reversed(created_ids))
    assert page["rows"] == legacy
    assert all(row["invoices"] == [] and row["payment_status"] == "no_invoice" for row in page["rows"])
    assert len(statements) == 4, statements
    invoice_query = next(statement for statement in statements if " from invoices " in statement)
    assert "in (" in invoice_query
    assert invoice_query.count("?") == count


def test_customer_order_page_applies_status_before_count(client, auth_headers):
    customer_id, created_ids = _seed_orders(1, status="cancelled")

    response = client.get(
        f"/api/customers/{customer_id}/orders",
        params={"status": "cancelled", "page": 1, "page_size": 1},
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == created_ids
    assert page["rows"][0]["status"] == "cancelled"


def test_customer_order_page_size_is_bounded(client, auth_headers):
    customer_id, _ = _seed_orders(1)
    response = client.get(
        f"/api/customers/{customer_id}/orders",
        params={"page": 1, "page_size": 501},
        headers=auth_headers,
    )
    assert response.status_code == 422, response.text


def test_customer_order_history_projects_response_fields_without_changing_totals():
    marker = uuid4().hex[:8].upper()
    with SessionLocal() as db:
        customer = Customer(name=f"PERF35 payment history customer {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"PERF35-PAY-{marker}",
            customer_id=customer.id,
            status="confirmed",
            total_amount=100,
        )
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"PERF35-INV-{marker}",
            amount=100,
            status="partially_paid",
        )
        db.add(invoice)
        db.flush()
        db.add(Payment(
            invoice_id=invoice.id,
            customer_id=customer.id,
            amount=25,
            payment_method="cash",
            notes="deposit",
        ))
        db.commit()
        customer_id = int(customer.id)
        legacy_sql = {
            "sales_orders": str(
                db.query(SalesOrder).filter(SalesOrder.customer_id == customer_id)
                .statement.compile(dialect=db.bind.dialect)
            ).lower(),
            "invoices": str(
                db.query(Invoice).filter(Invoice.sales_order_id == order.id)
                .statement.compile(dialect=db.bind.dialect)
            ).lower(),
            "payments": str(
                db.query(Payment).filter(Payment.invoice_id == invoice.id)
                .statement.compile(dialect=db.bind.dialect)
            ).lower(),
        }

    page, statements = _read(customer_id, page=1, page_size=10)
    assert page["total"] == 1
    assert page["rows"][0]["payment_status"] == "partial"
    invoice_row = page["rows"][0]["invoices"][0]
    assert (invoice_row["invoice_no"], invoice_row["amount"], invoice_row["raw_paid_amount"]) == (
        f"PERF35-INV-{marker}", 100.0, 25.0,
    )
    assert invoice_row["payments"][0]["notes"] == "deposit"

    sales_read = next(
        statement for statement in statements
        if " from sales_orders " in statement and not statement.startswith("select count")
    )
    invoice_read = next(statement for statement in statements if " from invoices " in statement)
    payment_read = next(statement for statement in statements if " from payments " in statement)
    assert "sales_orders.notes" not in sales_read
    assert "sales_orders.printing_attachments" not in sales_read
    assert "invoices.external_id" not in invoice_read
    assert "payments.customer_id" not in payment_read
    assert "payments.external_id" not in payment_read
    assert "sales_orders.notes" in legacy_sql["sales_orders"]
    assert "invoices.external_id" in legacy_sql["invoices"]
    assert "payments.customer_id" in legacy_sql["payments"]
