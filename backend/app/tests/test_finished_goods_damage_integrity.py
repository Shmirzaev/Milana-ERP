"""Damaged packages retain stock history without remaining sellable."""

from uuid import uuid4

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    SalesOrder,
    StockReservation,
    User,
)


def _damaged_stock_fixture():
    marker = uuid4().hex
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code=f"DMG-{marker}", name="Damage integrity", status="approved")
        order = SalesOrder(order_no=f"DMG-{marker}", order_type="branded_stock_sale", status="draft")
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="damage-integrity",
            source_record_id=marker,
            source_checksum="e" * 64,
            source_payload={"quantity": 10},
            imported_by=user.id,
        )
        db.add_all([model, order, receipt])
        db.flush()
        package = Package(
            package_no=f"DMG-{marker}",
            barcode=f"DMG-{marker}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="blue",
            total_quantity=10,
            capacity=10,
            status="received_in_storage",
        )
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=10,
            available_qty=10,
            reserved_qty=0,
            sold_qty=0,
            status="available",
        )
        db.add(stock)
        db.commit()
        return package.id, stock.id, order.id


def test_damaged_package_stock_cannot_be_reserved(client, auth_headers):
    package_id, stock_id, order_id = _damaged_stock_fixture()

    damaged = client.post(f"/api/packages/{package_id}/mark-damaged", headers=auth_headers)
    assert damaged.status_code == 200, damaged.text
    response = client.post(
        "/api/finished-goods/reserve",
        headers=auth_headers,
        params={"stock_id": stock_id, "quantity": 4, "sales_order_id": order_id},
    )

    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        package = db.get(Package, package_id)
        stock = db.get(FinishedGoodsStock, stock_id)
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock_id,
        ).all()
        assert package.status == "damaged"
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 10, 0, 0, "available",
        )
        assert reservations == []


def test_reserved_package_cannot_be_marked_damaged(client, auth_headers):
    package_id, stock_id, order_id = _damaged_stock_fixture()

    reserved = client.post(
        "/api/finished-goods/reserve",
        headers=auth_headers,
        params={"stock_id": stock_id, "quantity": 4, "sales_order_id": order_id},
    )
    assert reserved.status_code == 200, reserved.text

    damaged = client.post(f"/api/packages/{package_id}/mark-damaged", headers=auth_headers)

    assert damaged.status_code == 409, damaged.text
    with SessionLocal() as db:
        package = db.get(Package, package_id)
        stock = db.get(FinishedGoodsStock, stock_id)
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock_id,
        ).all()
        assert package.status == "received_in_storage"
        assert (stock.available_qty, stock.reserved_qty, stock.status) == (6, 4, "available")
        assert len(reservations) == 1
