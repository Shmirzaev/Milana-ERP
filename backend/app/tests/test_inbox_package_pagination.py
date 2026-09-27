from uuid import uuid4

import pytest
from sqlalchemy import event

from app.api.routes.inbox import finished_goods_packages
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    Model,
    Package,
    ProductionOrder,
    SalesOrder,
    StockReservation,
    User,
)


def _seed_ready_packages(count: int) -> str:
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"INBOX-{marker}", name=f"Inbox pagination {marker}")
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"INBOX-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            planned_quantity=count,
        )
        db.add(order)
        db.flush()
        sales_orders = [
            SalesOrder(
                order_no=f"INBOX-SO-{marker}-{index}",
                order_type="client_order",
                status="ready",
                total_amount=0,
            )
            for index in range(min(count, 3))
        ]
        db.add_all(sales_orders)
        db.flush()
        db.add_all(
            [
                Package(
                    package_no=f"INBOX-{marker}-{index:04d}",
                    barcode=f"INBOX-BC-{marker}-{index:04d}",
                    production_order_id=order.id,
                    sales_order_id=sales_orders[index % len(sales_orders)].id,
                    model_id=model.id,
                    color="Blue",
                    total_quantity=index + 1,
                    capacity=60,
                    status="received_in_storage",
                )
                for index in range(count)
            ]
        )
        db.commit()
    return marker


def _seed_reservation_order() -> tuple[int, str]:
    marker = uuid4().hex
    with SessionLocal() as db:
        model = Model(code=f"INBOX-RES-{marker}", name=f"Inbox reservation {marker}")
        db.add(model)
        db.flush()
        stock = FinishedGoodsStock(
            model_id=model.id,
            color="Blue",
            size="M",
            quantity=5,
            available_qty=5,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=1,
            selling_price=2,
            status="available",
        )
        order = SalesOrder(
            order_no=f"INBOX-RES-{marker}",
            order_type="branded_stock_sale",
            status="ready",
            total_amount=0,
        )
        db.add_all([stock, order])
        db.flush()
        db.add(StockReservation(sales_order_id=order.id, finished_goods_stock_id=stock.id, quantity=5))
        db.commit()
        return int(order.id), marker


@pytest.mark.parametrize("count", [1, 50, 401])
def test_finished_goods_inbox_packages_have_exact_bounded_pages(count):
    marker = _seed_ready_packages(count)
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        before_writes = (db.query(Package).count(), db.query(AuditLog).count())
        statements: list[str] = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select"):
                statements.append(normalized)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            first = finished_goods_packages(db, current, "ready", 1, 50, marker)
            second = finished_goods_packages(db, current, "ready", 2, 50, marker)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)

        assert first["total"] == count
        assert first["group_total"] == min(count, 3)
        assert len(first["rows"]) == min(count, 50)
        assert first["page"] == 1 and first["has_more"] is (count > 50)
        assert len(second["rows"]) == min(max(count - 50, 0), 50)
        assert second["page"] == 2 and second["has_more"] is (count > 100)
        assert set(row["package_no"] for row in first["rows"]).isdisjoint(
            row["package_no"] for row in second["rows"]
        )
        page_reads = [
            statement for statement in statements
            if " from packages " in statement and " limit " in statement and " offset " in statement
        ]
        assert len(page_reads) == 2
        assert all("packages.id desc" in statement for statement in page_reads)
        assert (db.query(Package).count(), db.query(AuditLog).count()) == before_writes


def test_finished_goods_inbox_package_search_escapes_wildcards_and_route_requires_auth(client):
    marker = _seed_ready_packages(3)
    with SessionLocal() as db:
        current = db.query(User).filter(User.email == "admin@example.com").one()
        exact = finished_goods_packages(db, current, "ready", 1, 50, f"{marker}-0001")
        missing = finished_goods_packages(db, current, "ready", 1, 50, "not-a-package")
        wildcard = finished_goods_packages(db, current, "ready", 1, 50, "%")
        assert exact["total"] == 1
        assert len(exact["rows"]) == 1
        assert missing["total"] == 0 and missing["rows"] == []
        assert wildcard["total"] == 0 and wildcard["rows"] == []
        headers = {"Authorization": f"Bearer {create_access_token(current.id)}"}

    assert client.get("/api/inbox/packages?status=ready").status_code == 401
    assert client.get(
        "/api/inbox/packages?status=ready&page_size=101",
        headers=headers,
    ).status_code == 422
    assert client.get(
        "/api/inbox/packages?status=invalid",
        headers=headers,
    ).status_code == 422


def test_finished_goods_screen_inbox_request_keeps_reservation_ready_to_ship_orders(client, auth_headers):
    sales_order_id, marker = _seed_reservation_order()

    response = client.get("/api/inbox?dept=FGS&tz=UTC", headers=auth_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    row = next((row for row in payload["ready_to_ship"] if row["sales_order_id"] == sales_order_id), None)
    assert row is not None
    assert row["sales_order_no"] == f"INBOX-RES-{marker}"
    assert row["pending_qty"] == 5
