"""Pack-count sales keep physical package contents authoritative."""
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    FinishedGoodsStock, Model, Package, PackageItem, SalesOrder, SalesOrderItem,
    Shipment, ShipmentPackage, StockReservation,
)


def ready_pack_candidates(
    db: Session, *, model_ids: set[int] | None = None, lock: bool = False,
) -> list[tuple[Package, list[FinishedGoodsStock]]]:
    """Return intact received packages, never synthetic bags or remaining pieces.

    Compare every size/color stock row with package-item evidence. An intact
    12-piece bag counts as one pack just like a 78-piece bag.
    """
    package_query = db.query(Package).join(Model, Model.id == Package.model_id).filter(
        Package.status.in_(("received_in_storage", "reserved")),
        Package.total_quantity > 0,
        Package.sales_order_id.is_(None),
        Model.catalog_scope == "standard",
        ~db.query(ShipmentPackage.id).join(Shipment, Shipment.id == ShipmentPackage.shipment_id).filter(
            ShipmentPackage.package_id == Package.id, Shipment.status != "cancelled",
        ).exists(),
        ~db.query(StockReservation.id).join(
            FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id,
        ).filter(or_(StockReservation.package_id == Package.id, FinishedGoodsStock.package_id == Package.id)).exists(),
    )
    if model_ids is not None:
        package_query = package_query.filter(Package.model_id.in_(model_ids))
    # Shipment correction and dispatch use this same global lock order.
    # Exclude attached/reserved packages before locking, then recheck evidence.
    if lock and db.bind and db.bind.dialect.name == "postgresql":
        package_query = package_query.with_for_update(of=Package)
    packages = package_query.order_by(Package.id).all()
    package_ids = [package.id for package in packages]
    if not package_ids:
        return []
    stock_query = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(package_ids))
    if lock and db.bind and db.bind.dialect.name == "postgresql":
        stock_query = stock_query.with_for_update(of=FinishedGoodsStock)
    stocks = stock_query.order_by(FinishedGoodsStock.id).all()
    stock_groups = defaultdict(list)
    for stock in stocks:
        stock_groups[stock.package_id].append(stock)
    item_groups = defaultdict(list)
    for item in db.query(PackageItem).filter(PackageItem.package_id.in_(package_ids)).all():
        item_groups[item.package_id].append(item)
    reserved_rows = db.query(StockReservation.finished_goods_stock_id, StockReservation.package_id).filter(
        or_(StockReservation.package_id.in_(package_ids),
            StockReservation.finished_goods_stock_id.in_([s.id for s in stocks])),
    ).all()
    reserved_stock_ids = {row[0] for row in reserved_rows}
    reserved_ids = {row[1] for row in reserved_rows} | {
        stock.package_id for stock in stocks if stock.id in reserved_stock_ids
    }
    attached_ids = {
        row[0] for row in db.query(ShipmentPackage.package_id).join(
            Shipment, Shipment.id == ShipmentPackage.shipment_id,
        ).filter(ShipmentPackage.package_id.in_(package_ids), Shipment.status != "cancelled").all()
    }
    result = []
    for package in packages:
        rows = stock_groups[package.id]
        if package.id in reserved_ids or package.id in attached_ids or not rows:
            continue
        if not (package.production_order_id or package.legacy_receipt_id or getattr(package, "manual_receipt_id", None)):
            continue
        if any(
            row.status != "available" or row.quantity <= 0 or row.available_qty != row.quantity
            or row.reserved_qty or row.sold_qty or row.model_id != package.model_id
            or row.sales_order_id is not None
            for row in rows
        ):
            continue
        stock_contents = defaultdict(int)
        item_contents = defaultdict(int)
        for row in rows:
            stock_contents[(row.model_id, row.color, row.size)] += row.quantity
        for item in item_groups[package.id]:
            item_contents[(item.model_id, item.color, item.size)] += item.quantity
        if stock_contents != item_contents or sum(stock_contents.values()) != package.total_quantity:
            continue
        result.append((package, rows))
    return result


def reserve_ready_packs(
    db: Session, *, so: SalesOrder, lines: list[SalesOrderItem], user_id: int,
) -> list[dict]:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.query(SalesOrder).filter(SalesOrder.id == so.id).with_for_update(of=SalesOrder).first()
    if db.query(StockReservation.id).filter(StockReservation.sales_order_id == so.id).first():
        raise HTTPException(409, "Stock has already been reserved for this sales order")
    candidates = ready_pack_candidates(db, model_ids={line.model_id for line in lines}, lock=True)
    allocations = []
    for line in lines:
        matching = [
            (package, rows) for package, rows in candidates
            if package.model_id == line.model_id
            and (line.brand_id is None or all(row.brand_id == line.brand_id for row in rows))
        ]
        count = int(line.requested_pack_count or 0)
        if len(matching) < count:
            raise HTTPException(409, f"Not enough complete packs: requested {count}, available {len(matching)}")
        allocations.append((line, matching[:count]))

    reservations = []
    for line, selected in allocations:
        line.quantity = sum(package.total_quantity for package, _ in selected)
        for package, rows in selected:
            for stock in rows:
                quantity = stock.quantity
                stock.available_qty = 0
                stock.reserved_qty = quantity
                stock.status = "reserved"
                db.add(StockReservation(
                    sales_order_id=so.id, finished_goods_stock_id=stock.id,
                    package_id=package.id, quantity=quantity, reserved_by=user_id,
                ))
                reservations.append({"stock_id": stock.id, "package_id": package.id, "qty": quantity})
    so.total_amount = sum(Decimal(str(line.unit_price)) * line.quantity for line in lines)
    so.status = "ready"
    return reservations
