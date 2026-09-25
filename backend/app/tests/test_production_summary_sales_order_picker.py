"""Production summary picker uses the existing bounded Sales Order search API."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import event

from app.api.routes.sales import list_sales_orders
from app.db.session import SessionLocal
from app.models import SalesOrder


def test_production_summary_sales_order_picker_pages_search_before_serialization():
    marker = uuid4().hex[:10].upper()
    with SessionLocal() as db:
        db.add_all([
            SalesOrder(
                order_no=f"SO-PO-PICK-{marker}-{index:04d}",
                order_type="client_order",
                status="draft",
                total_amount=0,
            )
            for index in range(401)
        ])
        db.commit()

    with SessionLocal() as db:
        statements = []

        def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(" ".join(statement.lower().split()))

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            first = list_sales_orders(
                db, SimpleNamespace(), order_type="client_order", q=marker,
                page=1, page_size=50, include_total=True,
            )
            second = list_sales_orders(
                db, SimpleNamespace(), order_type="client_order", q=marker,
                page=2, page_size=50, include_total=True,
            )
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

    assert first["total"] == second["total"] == 401
    assert len(first["rows"]) == len(second["rows"]) == 50
    assert {row["id"] for row in first["rows"]}.isdisjoint(
        row["id"] for row in second["rows"]
    )
    order_selects = [
        sql for sql in statements
        if " from sales_orders " in sql and " join customers " in sql and " limit ? offset ?" in sql
    ]
    assert len(order_selects) == 2
    assert all(" limit ? offset ?" in sql for sql in order_selects)
    assert not any(sql.startswith(("insert", "update", "delete")) for sql in statements)
