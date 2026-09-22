from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event

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
                status="draft",
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
                unit=item.unit,
                unit_cost=1,
                material_name=f"Bounded material {index}",
            )
            for index, order in enumerate(orders)
        ]
        db.add_all(lines)
        db.commit()
        return [int(order.id) for order in orders], [int(line.id) for line in lines]


def _read(**kwargs):
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().lower().startswith("select"):
                statements.append(" ".join(statement.lower().split()))

        event.listen(test_engine, "before_cursor_execute", capture)
        try:
            payload = list_purchase_orders(db, _current_user(), **kwargs)
        finally:
            event.remove(test_engine, "before_cursor_execute", capture)
        return payload, statements


def _dump(rows):
    return [PurchaseOrderOut.model_validate(row).model_dump(mode="json") for row in rows]


@pytest.mark.parametrize("count", [1, 50, 401])
def test_purchase_order_pages_preserve_legacy_and_bound_joined_lines(count):
    order_ids, line_ids = _seed_orders(count)
    returned_count = min(count, 50)

    page, statements = _read(page=1, page_size=50)
    legacy, _ = _read()
    page_rows = _dump(page["rows"])
    legacy_rows = _dump(legacy)

    assert page["total"] == count
    assert page["page"] == 1
    assert page["page_size"] == 50
    assert page["has_more"] is (count > 50)
    assert [row["id"] for row in page_rows] == list(reversed(order_ids))[:returned_count]
    assert page_rows == legacy_rows[:returned_count]
    assert [row["lines"][0]["id"] for row in page_rows] == list(reversed(line_ids))[:returned_count]
    assert all(row["lines"][0]["item_sku"] for row in page_rows)
    assert len(statements) == 2, statements
    row_query = statements[1]
    assert "left outer join purchase_order_lines" in row_query
    assert "left outer join items" in row_query
    assert " limit ? offset ?" in row_query


def test_purchase_order_page_http_contract_and_bound(client, auth_headers):
    [order_id], _ = _seed_orders(1)

    response = client.get(
        "/api/purchasing/orders?page=1&page_size=50",
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
    assert client.get(
        "/api/purchasing/orders?page_size=501",
        headers=auth_headers,
    ).status_code == 422
