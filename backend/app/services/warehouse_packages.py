"""Explicit, audited warehouse receipt and deletion of existing packages."""
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException

from app.models import (FinishedGoodsStock, Package, PackageChangeRequest, PackagePrintRun,
                        PackagePrintRunMember, ShipmentPackage, ShipmentScanLog, StockReservation,
                        WarehousePackReservation)
from app.models.shipment_review import PackageQuantityAdjustment
from app.models.stocktake import WarehouseStocktakeRow
from app.schemas.package_workflows import PrintRunReceiveIn
from app.services import package_workflows as workflows
from app.services.audit import log_action
from app.services.packaging_scope import require_package_access
from app.services.packages import prepare_locked_package_receive, receive_at_storage, sync_package_production_orders


def receive_order_packages(db, current, order_id, ids):
    if any(pid <= 0 or pid > 2147483647 for pid in ids) or len(set(ids)) != len(ids):
        raise HTTPException(422, "Select distinct valid packages")
    ids = sorted(set(ids))
    members = workflows.active_members(db).filter(PackagePrintRunMember.package_id.in_(ids)).all()
    runs = db.query(PackagePrintRun).filter(PackagePrintRun.id.in_({m.run_id for m in members})).order_by(
        PackagePrintRun.id).with_for_update().populate_existing().all()
    if any(not set(run.package_ids).issubset(ids) for run in runs):
        raise HTTPException(409, "Select the complete print run before receiving")
    gate = prepare_locked_package_receive(db, ids)
    packages = list(gate.packages_by_id.values())
    if len(packages) != len(ids) or any(p.production_order_id != order_id for p in packages):
        raise HTTPException(409, "Selected packages no longer belong to this order")
    for package in packages:
        require_package_access(current, package)
    # Replays only acknowledge already received packs; they cannot re-credit stock.
    if all(p.status == "received_in_storage" for p in packages):
        return {"count": len(packages)}
    if any(p.status != "packed" for p in packages):
        raise HTTPException(409, "Some selected packages are no longer awaiting receipt")
    stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).order_by(
        FinishedGoodsStock.id).with_for_update().all()
    for package in packages:
        expected, actual = defaultdict(int), defaultdict(int)
        for item in package.items:
            expected[(item.model_id, item.color, item.size)] += item.quantity
        rows = [row for row in stocks if row.package_id == package.id]
        for row in rows:
            actual[(row.model_id, row.color, row.size)] += row.quantity
        if (not rows or actual != expected or sum(actual.values()) != package.total_quantity
                or any(row.sold_qty or row.reserved_qty or row.available_qty != row.quantity or row.status != "available" for row in rows)):
            raise HTTPException(409, "Package stock evidence is inconsistent")
    for run in runs:
        workflows.receive_run(db, current, PrintRunReceiveIn(code=run.code))
    printed = {m.package_id for m in members}
    for package in packages:
        if package.id not in printed:
            receive_at_storage(db, package, None, current.id, receive_gate=gate, sync_production=False)
    sync_package_production_orders(db, (p.production_order_id for p in packages))
    log_action(db, current, "receive_order_packages", "ProductionOrder", order_id,
               new_value={"package_ids": ids, "count": len(ids)})
    return {"count": len(ids)}


def delete_warehouse_package(db, current, pid):
    members = workflows.active_members(db).filter(PackagePrintRunMember.package_id == pid).all()
    runs = db.query(PackagePrintRun).filter(PackagePrintRun.id.in_({m.run_id for m in members})).order_by(
        PackagePrintRun.id).with_for_update().populate_existing().all()
    package = db.query(Package).filter_by(id=pid).with_for_update().populate_existing().first()
    if not package:
        raise HTTPException(404, "Package not found")
    require_package_access(current, package)
    if (package.status != "received_in_storage" or package.sales_order_id
            or package.quantity_shortfall or package.dispatched_quantities):
        raise HTTPException(409, "Only unused received packages can be deleted")
    for model in (ShipmentPackage, ShipmentScanLog, StockReservation, WarehousePackReservation,
                  PackageQuantityAdjustment, WarehouseStocktakeRow, PackageChangeRequest):
        if db.query(model).filter_by(package_id=pid).first():
            raise HTTPException(409, "Package is reserved, linked or used and cannot be deleted")
    stocks = db.query(FinishedGoodsStock).filter_by(package_id=pid).order_by(FinishedGoodsStock.id).with_for_update().all()
    if (not stocks or sum(s.quantity for s in stocks) != package.total_quantity
            or any(s.sales_order_id or s.sold_qty or s.reserved_qty or s.available_qty != s.quantity or s.status != "available" for s in stocks)
            or db.query(StockReservation.id).filter(StockReservation.finished_goods_stock_id.in_([s.id for s in stocks])).first()):
        raise HTTPException(409, "Package stock is reserved, used or inconsistent")
    log_action(db, current, "delete_warehouse_package", "Package", pid, old_value=workflows.contents(package))
    from app.services.numbering import retire_label_numbers
    import re
    if re.fullmatch(r"PKG-\d{4}-\d+", package.package_no):
        retire_label_numbers(db, [package.package_no])
    for run in runs:
        run.deleted_package_ids = sorted(set(run.deleted_package_ids or []) | {pid})
        if set(run.deleted_package_ids) == set(run.package_ids):
            run.deleted_at = datetime.now(timezone.utc)
    for stock in stocks:
        db.delete(stock)
    order_id = package.production_order_id
    db.delete(package)
    db.flush()
    sync_package_production_orders(db, [order_id])
    return {"deleted_count": 1}
