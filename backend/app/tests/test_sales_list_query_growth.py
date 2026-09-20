from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.sales import list_sales_orders
from app.db.session import SessionLocal
from app.models import Customer, SalesOrder


def _orders(count):
    marker = f"SALESQ-{uuid4().hex}"
    with SessionLocal() as db:
        customers = [Customer(name=f"Buyer {marker}-{i}") for i in range(count)]
        db.add_all(customers)
        db.flush()
        orders = [SalesOrder(order_no=f"{marker}-{i}", customer_id=customer.id,
                             total_amount=i + 1, status="draft") for i, customer in enumerate(customers)]
        db.add_all(orders)
        db.commit()
        return marker, [row.id for row in orders]


def _read(**kwargs):
    with SessionLocal() as db:
        queries = []

        def capture(_conn, _cursor, statement, *_):
            if statement.lstrip().upper().startswith("SELECT"):
                queries.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            payload = list_sales_orders(db, None, **kwargs)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        return payload, queries


@pytest.mark.parametrize("count", [1, 50, 401])
def test_sales_list_customer_queries_are_bounded(count):
    marker, ids = _orders(count)
    rows, queries = _read(q=marker, page_size=500)
    assert [row["id"] for row in rows] == list(reversed(ids))
    assert all(row["customer"]["name"] == row["customer_name"] for row in rows)
    assert all(row["customer_name"].startswith(f"Buyer {marker}") for row in rows)
    assert len(queries) == 1


def test_sales_list_preserves_paging_total_filters_and_null_customer():
    marker, ids = _orders(5)
    with SessionLocal() as db:
        last = db.get(SalesOrder, ids[-1])
        last.customer_id = None
        db.commit()
    page, queries = _read(q=marker, page=2, page_size=2, status="draft", include_total=True)
    assert page["total"] == 5 and page["page"] == 2 and page["page_size"] == 2
    assert [row["id"] for row in page["rows"]] == [ids[2], ids[1]]
    assert len(queries) == 2
    all_rows, _ = _read(q=marker)
    assert all_rows[0]["customer"] is None and all_rows[0]["customer_name"] is None
    empty, _ = _read(q=marker, status="cancelled")
    assert empty == []


def test_sales_list_shared_customer_and_customer_filter():
    marker, ids = _orders(3)
    with SessionLocal() as db:
        customer_id = db.get(SalesOrder, ids[0]).customer_id
        customer_name = db.get(Customer, customer_id).name
        db.get(SalesOrder, ids[1]).customer_id = customer_id
        db.commit()
    rows, queries = _read(q=customer_name, customer_id=customer_id)
    assert [row["id"] for row in rows] == [ids[1], ids[0]]
    assert all(row["customer"] == {"id": customer_id, "name": customer_name} for row in rows)
    assert len(queries) == 1


def test_sales_list_requires_authentication(client):
    assert client.get("/api/sales-orders").status_code == 401
