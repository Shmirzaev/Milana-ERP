from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import event

from app.models import Customer, Invoice, SalesOrder
from app.services.finance import list_recent_invoices
from app.tests.conftest import TestSessionLocal


def test_recent_invoice_report_projects_only_serialized_fields():
    marker = uuid4().hex[:8]
    with TestSessionLocal() as db:
        customer = Customer(
            name=f"PERF35 invoice customer {marker}",
            address="Not selected by the finance report",
            notes="Not selected by the finance report",
        )
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"PERF35-INVOICE-{marker}", customer_id=customer.id)
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"PERF35-INV-{marker}",
            amount=Decimal("123.45"),
            status="paid",
            issued_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )
        db.add(invoice)
        db.commit()

        statements: list[str] = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from invoices " in normalized:
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            rows = list_recent_invoices(db, limit=50)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    row = next(item for item in rows if item["invoice_no"] == invoice.invoice_no)
    assert row == {
        "id": invoice.id,
        "invoice_no": invoice.invoice_no,
        "sales_order_id": order.id,
        "order_no": order.order_no,
        "customer": customer.name,
        "amount": 123.45,
        "status": "paid",
        "date": "2026-09-20T00:00:00+00:00",
    }
    assert len(statements) == 1
    selected_columns = statements[0].split(" from invoices", 1)[0]
    assert "invoices.invoice_no" in selected_columns
    assert "sales_orders.order_no" in selected_columns
    assert "customers.name" in selected_columns
    for omitted in (
        "invoices.updated_at",
        "invoices.external_id",
        "sales_orders.printing_attachments",
        "sales_orders.notes",
        "customers.address",
        "customers.notes",
    ):
        assert omitted not in selected_columns
