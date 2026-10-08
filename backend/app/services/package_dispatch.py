"""Partial dispatch keeps receipt contents and the physical label identity intact."""
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException

from app.models import Package, PackageItem, PackageScanLog, ShipmentPackage, StockReservation
from app.services.audit import log_action


def remaining_quantity(package):
    return package.total_quantity - (package.dispatched_quantity or 0)


def remaining_item_quantity(package, item):
    return item.quantity - (package.dispatched_quantities or {}).get(str(item.id), 0)


def selected_items(shipment, package, items):
    selection = (shipment.dispatch_snapshot or {}).get("package_quantities", {}).get(str(package.id))
    return {str(item.id): selection.get(str(item.id), 0) if selection is not None
            else remaining_item_quantity(package, item) for item in items}


def select_dispatch_quantity(db, shipment, pid, payload, user):
    if shipment.status not in {"draft", "created"}:
        raise HTTPException(409, "Change shipment quantities before dispatch")
    package = db.query(Package).filter_by(id=pid).with_for_update().populate_existing().first()
    link = db.query(ShipmentPackage).filter_by(shipment_id=shipment.id, package_id=pid).first()
    if not package or not link:
        raise HTTPException(404, "Package is not attached to this shipment")
    if package.status not in {"received_in_storage", "reserved"} or link.quantity != payload.expected_quantity:
        raise HTTPException(409, "Package quantity changed; reload before editing")
    items = db.query(PackageItem).filter_by(package_id=pid).order_by(PackageItem.id).all()
    quantities = {str(line.item_id): line.quantity for line in payload.items}
    if len(quantities) != len(payload.items) or set(quantities) != {str(item.id) for item in items}:
        raise HTTPException(422, "Supply each package item exactly once")
    if any(quantities[str(item.id)] > remaining_item_quantity(package, item) for item in items):
        raise HTTPException(409, "Shipment quantity exceeds the pieces remaining in this package")
    total = sum(quantities.values())
    if total <= 0:
        raise HTTPException(409, "Remove the whole package instead of selecting zero pieces")
    from app.services.packaging_scope import require_package_access
    require_package_access(user, package)
    before = link.quantity
    selections = {**(shipment.dispatch_snapshot or {}).get("package_quantities", {}), str(pid): quantities}
    shipment.dispatch_snapshot = {**(shipment.dispatch_snapshot or {}), "package_quantities": selections}
    link.quantity = total
    log_action(db, user, "select_shipment_package_quantity", "Shipment", shipment.id,
               old_value={"package_id": pid, "quantity": before},
               new_value={"package_id": pid, "quantity": total, "items": quantities, "reason": payload.reason})
    db.flush()


def dispatch_selected(db, shipment, package, stocks, user):
    from app.services.packages import _require_warehouse_package
    _require_warehouse_package(db, package)
    items = db.query(PackageItem).filter_by(package_id=package.id).order_by(PackageItem.id).all()
    quantities = selected_items(shipment, package, items)
    link = next(link for link in shipment.packages if link.package_id == package.id)
    if sum(quantities.values()) != link.quantity or any(
            qty < 0 or qty > remaining_item_quantity(package, item)
            for item in items for qty in [quantities[str(item.id)]]):
        raise HTTPException(409, "Selected contents changed; review the shipment again")
    grouped = defaultdict(int)
    expected, actual, expected_sold, actual_sold = (defaultdict(int) for _ in range(4))
    for item in items:
        key = (item.model_id, item.color, item.size)
        grouped[key] += quantities[str(item.id)]
        expected[key] += item.quantity
        expected_sold[key] += (package.dispatched_quantities or {}).get(str(item.id), 0)
    for stock in stocks:
        key = (stock.model_id, stock.color, stock.size)
        actual[key] += stock.quantity
        actual_sold[key] += stock.sold_qty
    if expected != actual or expected_sold != actual_sold:
        raise HTTPException(409, "Package contents and warehouse stock do not balance")
    reservations = db.query(StockReservation).filter_by(package_id=package.id).order_by(
        StockReservation.id).with_for_update().all()
    if any(row.sales_order_id != shipment.sales_order_id for row in reservations):
        raise HTTPException(409, "Package is reserved for another order")
    for stock in stocks:
        key = (stock.model_id, stock.color, stock.size)
        take = min(grouped[key], stock.available_qty + stock.reserved_qty)
        grouped[key] -= take
        own = [r for r in reservations if r.finished_goods_stock_id == stock.id]
        if sum(r.quantity for r in own) != stock.reserved_qty:
            raise HTTPException(409, "Package reservations do not balance")
        # Dispatch the selected pieces and release the rest back to this same pack.
        stock.available_qty += stock.reserved_qty - take
        stock.reserved_qty = 0
        stock.sold_qty += take
        stock.status = "available" if stock.available_qty else "sold"
        for reservation in own:
            db.delete(reservation)
    if any(grouped.values()):
        raise HTTPException(409, "Selected quantity is not available in warehouse stock")
    previous = package.dispatched_quantities or {}
    package.dispatched_quantities = {str(item.id): previous.get(str(item.id), 0) + quantities[str(item.id)] for item in items}
    package.dispatched_quantity = sum(package.dispatched_quantities.values())
    package.status = "received_in_storage" if remaining_quantity(package) else "shipped"
    if package.status == "shipped":
        package.shipped_at = datetime.now(timezone.utc)
        package.storage_cell = package.storage_shelf = package.storage_placed_at = None
    db.add(PackageScanLog(package_id=package.id, scanned_by=user.id, scan_type="shipped"))
    log_action(db, user, "dispatch_package_pieces", "Package", package.id,
               new_value={"shipment_id": shipment.id, "quantity": link.quantity,
                          "remaining_quantity": remaining_quantity(package), "barcode": package.barcode})
    db.flush()
