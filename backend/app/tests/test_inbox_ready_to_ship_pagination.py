from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes import inbox
from app.models import (
    Customer,
    FinishedGoodsStock,
    Model,
    Package,
    ProductionOrder,
    SalesOrder,
    SalesOrderItem,
    Shipment,
    StockReservation,
)
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("order_count", [0, 1, 50, 401])
def test_ready_to_ship_orders_page_with_exact_total_and_complete_selected_details(monkeypatch, order_count):
    suffix = uuid4().hex[:8]
    monkeypatch.setattr(inbox, "require_operational_department_access", lambda *_args: None)
    monkeypatch.setattr(inbox, "user_permissions", lambda _user: ["*"])
    with TestSessionLocal() as db:
        baseline = inbox.department_inbox(db, SimpleNamespace(department_id=None), dept="FGS")
        baseline_total = baseline["ready_to_ship_total"]
        baseline_ids = [row["sales_order_id"] for row in baseline["ready_to_ship"]]
        customer = Customer(name=f"Pagination customer {suffix}", address="Warehouse road")
        model = Model(code=f"INBOX-PAGE-{suffix}", name="Paged reservation model")
        production_order = ProductionOrder(
            production_no=f"INBOX-PROD-{suffix}",
            production_type="client_order",
            model_id=model.id if model.id else None,
            planned_quantity=4,
        )
        db.add_all([customer, model])
        db.flush()
        production_order.model_id = model.id
        db.add(production_order)
        db.flush()

        orders = []
        for index in range(order_count):
            order = SalesOrder(
                order_no=f"INBOX-PAGE-{suffix}-{index:02}",
                customer_id=customer.id,
                order_type="branded_stock_sale",
                status="ready",
            )
            db.add(order)
            db.flush()
            stock = FinishedGoodsStock(
                sales_order_id=order.id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=4,
                reserved_qty=4,
                status="reserved",
            )
            db.add(stock)
            db.flush()
            db.add(SalesOrderItem(
                sales_order_id=order.id,
                model_id=model.id,
                color="navy",
                size="M",
                quantity=4,
                unit_price=12,
            ))
            if index == 0:
                package = Package(
                    package_no=f"INBOX-PAGE-PACKAGE-{suffix}",
                    barcode=f"INBOX-PAGE-PACKAGE-{suffix}",
                    production_order_id=production_order.id,
                    sales_order_id=order.id,
                    model_id=model.id,
                    color="navy",
                    total_quantity=3,
                    capacity=60,
                    status="received_in_storage",
                )
                db.add(package)
                db.flush()
                db.add(StockReservation(
                    sales_order_id=order.id,
                    finished_goods_stock_id=stock.id,
                    package_id=package.id,
                    quantity=3,
                ))
                pending_stock = FinishedGoodsStock(
                    sales_order_id=order.id,
                    model_id=model.id,
                    color="navy",
                    size="L",
                    quantity=4,
                    reserved_qty=4,
                    status="reserved",
                )
                db.add(pending_stock)
                db.flush()
                db.add(StockReservation(
                    sales_order_id=order.id,
                    finished_goods_stock_id=pending_stock.id,
                    quantity=4,
                ))
            else:
                db.add(StockReservation(
                    sales_order_id=order.id,
                    finished_goods_stock_id=stock.id,
                    quantity=4,
                ))
            orders.append(order)

        if orders:
            db.add_all([
                Shipment(
                    sales_order_id=orders[0].id,
                    shipment_no=f"INBOX-PAGE-OLD-{suffix}",
                    status="created",
                ),
                Shipment(
                    sales_order_id=orders[0].id,
                    shipment_no=f"INBOX-PAGE-LATEST-{suffix}",
                    status="shipped",
                ),
            ])
        db.commit()
        order_ids = [int(order.id) for order in orders]

    with TestSessionLocal() as db:
        first = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_offset=baseline_total,
        )
        last = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_offset=baseline_total + max(0, order_count - 1),
        )
        second = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_offset=baseline_total + 50,
        )
        searched = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_q=suffix.lower(),
        )
        unmatched = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_q="no matching order or customer",
        )
        wildcard = inbox.department_inbox(
            db,
            SimpleNamespace(department_id=None),
            dept="FGS",
            ready_to_ship_limit=50,
            ready_to_ship_q=f"%{suffix[:5]}%",
        )
        legacy = inbox.department_inbox(db, SimpleNamespace(department_id=None), dept="FGS")

    assert first["ready_to_ship_total"] == baseline_total + order_count
    assert searched["ready_to_ship_total"] == order_count
    assert [row["sales_order_id"] for row in searched["ready_to_ship"]] == order_ids[:50]
    assert unmatched["ready_to_ship_total"] == 0
    assert unmatched["ready_to_ship"] == []
    assert wildcard["ready_to_ship_total"] == 0
    assert last["ready_to_ship_total"] == baseline_total + order_count
    assert [row["sales_order_id"] for row in legacy["ready_to_ship"]] == baseline_ids + order_ids
    assert legacy["ready_to_ship_total"] == baseline_total + order_count
    assert [row["sales_order_id"] for row in first["ready_to_ship"]] == order_ids[:50]
    assert [row["sales_order_id"] for row in last["ready_to_ship"]] == (
        order_ids[-1:] if order_ids else []
    )
    if order_count > 50:
        assert [row["sales_order_id"] for row in second["ready_to_ship"]] == order_ids[50:100]
    else:
        assert second["ready_to_ship"] == []

    if order_ids:
        first_order = first["ready_to_ship"][0]
        assert first_order["quantity"] == 3
        assert first_order["pending_qty"] == 4
        assert first_order["reserved_qty"] == 7
        assert first_order["packages"] == 1
        assert first_order["package_lines"] == [{
            "package_id": first_order["package_lines"][0]["package_id"],
            "package_no": f"INBOX-PAGE-PACKAGE-{suffix}",
            "reserved_qty": 3,
            "status": "received_in_storage",
        }]
        assert first_order["item_lines"][0]["model_code"] == f"INBOX-PAGE-{suffix}"
        assert first_order["item_lines"][0]["quantity"] == 4
        assert first_order["shipment_no"] == f"INBOX-PAGE-LATEST-{suffix}"
        assert first_order["shipment_status"] == "shipped"


def test_ready_to_ship_page_requires_auth_and_rejects_oversized_page(client, auth_headers):
    assert client.get("/api/inbox?dept=FGS&ready_to_ship_limit=1").status_code == 401
    assert client.get(
        "/api/inbox?dept=FGS&ready_to_ship_limit=101",
        headers=auth_headers,
    ).status_code == 422
    assert client.get(
        "/api/inbox?dept=FGS&ready_to_ship_limit=50&ready_to_ship_q=" + "x" * 101,
        headers=auth_headers,
    ).status_code == 422

