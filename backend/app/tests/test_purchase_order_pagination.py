from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import joinedload

from app.api.routes.purchasing import list_purchase_orders
from app.models import Item, PurchaseOrder, PurchaseOrderLine
from app.schemas.purchasing import PurchaseOrderOut
from app.tests.conftest import TestSessionLocal, test_engine


def _current_user():
    return SimpleNamespace(
        role=SimpleNamespace(name="", permissions=[]),
        extra_permissions=[],
        access_policy={},
        factory_code="MIL",
        session_factory_code="MIL",
    )


def _seed_orders(count):
    marker = uuid4().hex[:10]
    with TestSessionLocal() as db:
        item = db.query(Item).order_by(Item.id).first()
        assert item is not None
        orders = [
            PurchaseOrder(
                po_no=f"PERF35-PO-{marker}-{index:04d}",
                status="sent",
            )
            for index in range(count)
        ]
        db.add_all(orders)
        db.flush()
        lines = [
            PurchaseOrderLine(
                purchase_order_id=order.id,
                item_id=item.id,
                ordered_quantity=index + 1,
                received_quantity=0,
                unit="kg",
                unit_cost=1,
                material_name=f"Bounded material {marker} {index}",
            )
            for index, order in enumerate(orders)
        ]
        db.add_all(lines)
        db.commit()
        return [int(order.id) for order in orders], [int(line.id) for line in lines]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []
        writes = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))
            else:
                writes.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_purchase_orders(db, _current_user(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements, writes


def _dump(rows):
    return [PurchaseOrderOut.model_validate(row).model_dump(mode="json") for row in rows]


def _legacy_select_column_count():
    with TestSessionLocal() as db:
        statement = (
            db.query(PurchaseOrder)
            .options(joinedload(PurchaseOrder.lines))
            .order_by(PurchaseOrder.id.desc())
            .limit(50)
            .statement
        )
        sql = str(statement.compile(dialect=test_engine.dialect)).lower()
        return sql.split(" from ", 1)[0].count(" as ")


@pytest.mark.parametrize("count", [1, 50, 401])
def test_purchase_order_pages_preserve_legacy_and_bound_joined_lines(count):
    order_ids, line_ids = _seed_orders(count)
    returned_count = min(count, 50)

    page, statements, writes = _read(page=1, page_size=50)
    page_two, _, page_two_writes = _read(page=2, page_size=50)
    legacy, _, legacy_writes = _read()
    marker = legacy[0].po_no.split("-")[2]
    searched, _, search_writes = _read(page=1, page_size=50, receivable_only=True, q=f"Bounded material {marker}")
    wildcard, _, wildcard_writes = _read(page=1, page_size=50, receivable_only=True, q=f"%Bounded material {marker}%")
    oldest_id = order_ids[0]
    targeted, target_statements, target_writes = _read(order_id=oldest_id)
    page_rows = _dump(page["rows"])
    legacy_rows = _dump(legacy)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page_rows] == list(reversed(order_ids))[:returned_count]
    assert page_rows == legacy_rows[:returned_count]
    page_two_rows = _dump(page_two["rows"])
    assert page_two["total"] == count
    assert len(page_two_rows) == min(max(0, count - 50), 50)
    assert {row["id"] for row in page_rows}.isdisjoint({row["id"] for row in page_two_rows})
    assert searched["total"] == count
    assert [row.id for row in searched["rows"]] == list(reversed(order_ids))[:returned_count]
    assert wildcard["total"] == 0 and wildcard["rows"] == []
    assert searched["supplier_totals"] == [{
        "key": "supplier-name:",
        "total_ordered_kg": float(count * (count + 1) / 2),
    }]
    assert [row.id for row in targeted] == [oldest_id], "recovery lookup must not depend on the visible page"
    assert len(target_statements) == 1
    assert writes == page_two_writes == legacy_writes == search_writes == wildcard_writes == target_writes == []
    assert [row["lines"][0]["id"] for row in page_rows] == list(reversed(line_ids))[:returned_count]
    assert all(row["lines"][0]["item_sku"] for row in page_rows)
    assert len(statements) == 2, statements
    row_query = statements[1]
    assert "left outer join purchase_order_lines" in row_query
    assert "left outer join items" in row_query
    assert " limit ? offset ?" in row_query
    assert "request_no" in row_query
    assert "name" in row_query
    assert "sku" in row_query
    assert "composition_json" not in row_query
    assert "address" not in row_query
    assert "warehouses_1.type" not in row_query
    assert "purchase_requests_1.notes" not in row_query
    selected_column_count = row_query.split(" from ", 1)[0].count(" as ")
    assert selected_column_count < _legacy_select_column_count()


def test_purchase_order_page_http_contract_and_bound(client, auth_headers):
    order_ids, _ = _seed_orders(1)
    [order_id] = order_ids

    response = client.get(
        "/api/purchasing/orders?page=1&page_size=50&receivable_only=true",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert [row["id"] for row in page["rows"]] == [order_id]
    assert page["rows"][0]["lines"][0]["item_sku"]
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is False
    assert page["supplier_totals"] == [{"key": "supplier-name:", "total_ordered_kg": 1.0}]
    targeted = client.get(f"/api/purchasing/orders?order_id={order_id}", headers=auth_headers)
    assert targeted.status_code == 200, targeted.text
    assert [row["id"] for row in targeted.json()] == [order_id]
    assert client.get("/api/purchasing/orders?page=1").status_code in (401, 403)
    assert client.get(
        "/api/purchasing/orders?page_size=501",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/purchasing/orders?q=" + "x" * 101,
        headers=auth_headers,
    ).status_code == 422


def test_receiving_orders_filter_status_and_search_before_count():
    order_ids, _ = _seed_orders(2)
    with TestSessionLocal() as db:
        db.query(PurchaseOrder).filter(PurchaseOrder.id == order_ids[0]).update({"status": "draft"})
        db.commit()

    page, _, writes = _read(page=1, page_size=50, receivable_only=True, q="Bounded material")

    assert page["total"] == 1
    assert [row.id for row in page["rows"]] == [order_ids[1]]
    assert page["supplier_totals"] == [{"key": "supplier-name:", "total_ordered_kg": 2.0}]
    assert writes == []
