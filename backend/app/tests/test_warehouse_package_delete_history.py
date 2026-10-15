"""Deleting unused stock preserves count evidence and explains operational blockers."""
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    AuditLog, Customer, FinishedGoodsStock, LegacyStockReceipt, Package, PackageBarcodeAlias,
    PackageChangeRequest, SalesOrder, Shipment, ShipmentPackage, ShipmentScanLog,
    StockReservation, User, WarehousePackReservation,
)
from app.models.shipment_review import PackageQuantityAdjustment
from app.models.stocktake import WarehouseStocktakeRow
from app.tests.test_package_workflows import warehouse  # noqa: F401
from app.tests.test_warehouse_stocktake import BASE, detail, packs, scan, start  # noqa: F401


def count_evidence():
    with SessionLocal() as db:
        return db.execute(select(WarehouseStocktakeRow.__table__).order_by(WarehouseStocktakeRow.id)).all()


def test_delete_preserves_open_and_completed_counts_and_exports(client, auth_headers, warehouse, packs):
    active, completed = start(client, auth_headers), start(client, auth_headers)
    for cid in (active, completed):
        scan(client, auth_headers, cid, "OLD-UNIQUE")
    assert client.post(f"{BASE}/{completed}/complete", headers=auth_headers).status_code == 200
    frozen = detail(client, auth_headers, completed)
    exported = client.get(f"{BASE}/{completed}/export.csv", headers=auth_headers)
    assert exported.status_code == 200
    evidence = count_evidence()
    with SessionLocal() as db:
        receipts = db.execute(select(LegacyStockReceipt.__table__)).all()
        unrelated = db.execute(select(FinishedGoodsStock.__table__).where(
            FinishedGoodsStock.package_id != packs[0])).all()

    response = client.delete(f"/api/packages/warehouse/{packs[0]}", headers=warehouse)
    assert response.status_code == 200, response.text
    assert response.json() == {"deleted_count": 1}
    assert count_evidence() == evidence
    assert detail(client, auth_headers, completed) == frozen
    assert client.get(f"{BASE}/{completed}/export.csv", headers=auth_headers).content == exported.content
    current = detail(client, auth_headers, active)
    row = next(row for row in current["rows"] if row["package_id"] == packs[0])
    assert row["snapshot"]["package_no"] == "COUNT-0"
    assert row["scan_snapshot"]["quantity"] == row["scanned_pieces"] == 60
    assert row["scan_code"] == "OLD-UNIQUE" and row["scanned_by"]
    assert row["result"] == "found" and row["changed"] and row["current"] == {}
    assert current["summary"]["scanned_packages"] == 1
    assert current["summary"]["scanned_pieces"] == 60
    live_export = client.get(f"{BASE}/{active}/export.csv", headers=auth_headers)
    assert live_export.status_code == 200 and "COUNT-0" in live_export.text
    assert client.post(f"{BASE}/{active}/complete", headers=auth_headers).status_code == 200
    assert detail(client, auth_headers, active)["summary"]["scanned_pieces"] == 60
    with SessionLocal() as db:
        assert db.get(Package, packs[0]) is None
        assert not db.query(FinishedGoodsStock).filter_by(package_id=packs[0]).count()
        assert not db.query(PackageBarcodeAlias).filter_by(package_id=packs[0]).count()
        assert db.execute(select(LegacyStockReceipt.__table__)).all() == receipts
        assert db.execute(select(FinishedGoodsStock.__table__).where(
            FinishedGoodsStock.package_id != packs[0])).all() == unrelated
        assert db.query(AuditLog).filter_by(action="delete_warehouse_package", entity_id=packs[0]).count() == 1
    assert client.delete(f"/api/packages/warehouse/{packs[0]}", headers=warehouse).status_code == 404


@pytest.mark.parametrize("condition,reason", [
    ("status", "Only packages received in the warehouse can be deleted"),
    ("order", "Package is linked to a sales order and cannot be deleted"),
    ("shortfall", "Package has a recorded quantity shortfall and cannot be deleted"),
    ("dispatch", "Package has dispatched pieces and cannot be deleted"),
    ("shipment", "Package is linked to a shipment and cannot be deleted"),
    ("shipment_scan", "Package has shipment scan history and cannot be deleted"),
    ("reservation", "Package has stock reservation history and cannot be deleted"),
    ("warehouse_reservation", "Package has a warehouse reservation and cannot be deleted"),
    ("adjustment", "Package has quantity adjustment history and cannot be deleted"),
    ("request", "Package has an edit or delete request and cannot be deleted"),
    ("missing_stock", "Package stock is missing or does not match the package quantity"),
    ("stock_quantity", "Package stock is missing or does not match the package quantity"),
    ("stock_order", "Package stock is linked to a sales order and cannot be deleted"),
    ("sold", "Package stock has sold pieces and cannot be deleted"),
    ("reserved", "Package stock is reserved and cannot be deleted"),
    ("unavailable", "Package stock is not fully available and cannot be deleted"),
    ("stock_status", "Package stock is not fully available and cannot be deleted"),
    ("stock_reservation", "Package stock has reservation history and cannot be deleted"),
])
def test_count_history_does_not_bypass_operational_guards(client, auth_headers, warehouse, packs, condition, reason):
    cid = start(client, auth_headers)
    scan(client, auth_headers, cid, "COUNT-0")
    pid = packs[0]
    with SessionLocal() as db:
        package = db.get(Package, pid)
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        order = SalesOrder(order_no="DELETE-GUARD")
        shipment = Shipment(shipment_no="DELETE-GUARD")
        db.add_all([order, shipment])
        db.flush()
        user_id = db.query(User).first().id
        if condition == "status":
            package.status = "packed"
        elif condition == "order":
            package.sales_order_id = order.id
        elif condition == "shortfall":
            package.quantity_shortfall = 1
        elif condition == "dispatch":
            package.dispatched_quantities = {"1": 1}
        elif condition == "shipment":
            db.add(ShipmentPackage(shipment_id=shipment.id, package_id=pid, quantity=60))
        elif condition == "shipment_scan":
            db.add(ShipmentScanLog(shipment_id=shipment.id, package_id=pid, scanned_code=package.barcode, scan_result="ok"))
        elif condition in {"reservation", "stock_reservation"}:
            db.add(StockReservation(sales_order_id=order.id, finished_goods_stock_id=stock.id,
                                    package_id=pid if condition == "reservation" else None, quantity=1))
        elif condition == "warehouse_reservation":
            db.add(WarehousePackReservation(package_id=pid, customer_id=db.query(Customer).first().id,
                                            quantity=60, reserved_by=user_id))
        elif condition == "adjustment":
            db.add(PackageQuantityAdjustment(package_id=pid, shipment_id=shipment.id, delta=0,
                                            before_json={}, after_json={}, reason="Previous correction", created_by=user_id))
        elif condition == "request":
            db.add(PackageChangeRequest(package_id=pid, package_no=package.package_no, request_type="edit"))
        elif condition == "missing_stock":
            db.delete(stock)
        elif condition == "stock_quantity":
            stock.quantity -= 1
        elif condition == "stock_order":
            stock.sales_order_id = order.id
        elif condition == "sold":
            stock.sold_qty = 1
            stock.available_qty -= 1
        elif condition == "reserved":
            stock.reserved_qty = 1
            stock.available_qty -= 1
        elif condition == "unavailable":
            stock.available_qty -= 1
        elif condition == "stock_status":
            stock.status = "damaged"
        db.commit()
        before = [db.execute(select(model.__table__)).all() for model in
                  (Package, FinishedGoodsStock, WarehouseStocktakeRow, AuditLog)]
    response = client.delete(f"/api/packages/warehouse/{pid}", headers=warehouse)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == reason
    with SessionLocal() as db:
        assert [db.execute(select(model.__table__)).all() for model in
                (Package, FinishedGoodsStock, WarehouseStocktakeRow, AuditLog)] == before
