from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    Brand, FinishedGoodsStock, Model, Package, PackageItem, ProductionOrder,
    SalesOrder, Shipment, ShipmentPackage, StockReservation, User,
)
from app.schemas.tracking import FinishedGoodsStockOut
from app.services.audit import log_action
router = APIRouter(prefix="/finished-goods", tags=["finished_goods"])
PackageBrand = aliased(Brand)


def _stock_payload(
    stock: FinishedGoodsStock,
    *,
    model_code: str | None = None,
    model_name: str | None = None,
    brand_name: str | None = None,
) -> dict:
    return {
        "id": stock.id,
        "production_order_id": stock.production_order_id,
        "sales_order_id": stock.sales_order_id,
        "package_id": stock.package_id,
        "model_id": stock.model_id,
        "model_code": model_code,
        "model_name": model_name,
        "brand_id": stock.brand_id,
        "brand_name": brand_name,
        "collection_id": stock.collection_id,
        "color": stock.color,
        "size": stock.size,
        "quantity": stock.quantity,
        "available_qty": stock.available_qty,
        "reserved_qty": stock.reserved_qty,
        "sold_qty": stock.sold_qty,
        "cost_per_piece": float(stock.cost_per_piece or 0),
        "selling_price": float(stock.selling_price or 0),
        "warehouse_id": stock.warehouse_id,
        "status": stock.status,
    }


@router.get("", response_model=list[FinishedGoodsStockOut])
def list_stock(db: DbSession, _: CurrentUser,
               model_id: int | None = None, status: str | None = None, brand_id: int | None = None):
    qry = (
        db.query(
            FinishedGoodsStock,
            Model.code.label("model_code"),
            Model.name.label("model_name"),
            Brand.name.label("brand_name"),
        )
        .outerjoin(Model, Model.id == FinishedGoodsStock.model_id)
        .outerjoin(Brand, Brand.id == FinishedGoodsStock.brand_id)
    )
    if model_id: qry = qry.filter(FinishedGoodsStock.model_id == model_id)
    if status: qry = qry.filter(FinishedGoodsStock.status == status)
    if brand_id: qry = qry.filter(FinishedGoodsStock.brand_id == brand_id)
    return [
        _stock_payload(
            stock,
            model_code=model_code,
            model_name=model_name,
            brand_name=brand_name,
        )
        for stock, model_code, model_name, brand_name in qry.order_by(FinishedGoodsStock.id.desc()).all()
    ]


@router.get("/branded-stock", response_model=list[FinishedGoodsStockOut])
def list_branded(db: DbSession, _: CurrentUser):
    rows = (
        db.query(
            FinishedGoodsStock,
            Model.code.label("model_code"),
            Model.name.label("model_name"),
            func.coalesce(Brand.name, PackageBrand.name).label("brand_name"),
        )
        .outerjoin(ProductionOrder, ProductionOrder.id == FinishedGoodsStock.production_order_id)
        .outerjoin(Package, Package.id == FinishedGoodsStock.package_id)
        .outerjoin(Model, Model.id == FinishedGoodsStock.model_id)
        .outerjoin(Brand, Brand.id == FinishedGoodsStock.brand_id)
        .outerjoin(PackageBrand, PackageBrand.id == Package.brand_id)
        .filter(
            FinishedGoodsStock.available_qty > 0,
            FinishedGoodsStock.status == "available",
            (
                FinishedGoodsStock.brand_id.isnot(None)
                | (ProductionOrder.production_type == "branded_stock")
                | (Package.brand_id.isnot(None))
                | (Package.legacy_receipt_id.isnot(None))
                | (Package.manual_receipt_id.isnot(None))
            ),
        )
        .order_by(FinishedGoodsStock.id.desc())
        .all()
    )
    return [
        _stock_payload(
            stock,
            model_code=model_code,
            model_name=model_name,
            brand_name=brand_name,
        )
        for stock, model_code, model_name, brand_name in rows
    ]


def _reserve_manual_package(db, current, stock, quantity, sales_order_id):
    # Match receipt/correction locking: package first, then its contents/stock.
    package = (
        db.query(Package).filter(Package.id == stock.package_id)
        .with_for_update(of=Package).populate_existing().one()
    )
    if not package.manual_receipt_id or package.status not in {"received_in_storage", "reserved"}:
        raise HTTPException(409, "Manual package is not available for reservation")
    if quantity != package.total_quantity or quantity <= 0:
        raise HTTPException(409, "Reserve the entire manual package quantity in one request")
    order = db.get(SalesOrder, sales_order_id)
    if not order:
        raise HTTPException(404, "Sales order not found")
    if order.status in {"shipped", "delivered", "closed", "cancelled"}:
        raise HTTPException(409, "Sales order is no longer open for reservation")
    items = (
        db.query(PackageItem).filter(PackageItem.package_id == package.id)
        .order_by(PackageItem.id).with_for_update(of=PackageItem).populate_existing().all()
    )
    rows = (
        db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package.id)
        .order_by(FinishedGoodsStock.id).with_for_update(of=FinishedGoodsStock)
        .populate_existing().all()
    )
    if stock.id not in {row.id for row in rows} or not items:
        raise HTTPException(409, "Manual package stock changed; reload before reserving")
    if package.sales_order_id or any(
        row.quantity <= 0 or row.available_qty != row.quantity or row.reserved_qty or row.sold_qty
        or row.status != "available" or row.sales_order_id is not None or row.model_id != package.model_id
        for row in rows
    ):
        raise HTTPException(409, "Manual package must be completely available")
    if db.query(StockReservation.id).filter(or_(
        StockReservation.package_id == package.id,
        StockReservation.finished_goods_stock_id.in_([row.id for row in rows]),
    )).first():
        raise HTTPException(409, "Manual package already has a reservation")
    if db.query(ShipmentPackage.id).join(Shipment).filter(
        ShipmentPackage.package_id == package.id, Shipment.status != "cancelled",
    ).first():
        raise HTTPException(409, "Manual package is already attached to a shipment")
    stock_contents, item_contents = defaultdict(int), defaultdict(int)
    for row in rows:
        stock_contents[(row.model_id, row.color, row.size)] += row.quantity
    for item in items:
        item_contents[(item.model_id, item.color, item.size)] += item.quantity
    if stock_contents != item_contents or sum(stock_contents.values()) != package.total_quantity:
        raise HTTPException(409, "Manual package contents and warehouse stock do not balance")
    for row in rows:
        row.available_qty = 0
        row.reserved_qty = row.quantity
        row.status = "reserved"
        db.add(StockReservation(
            sales_order_id=sales_order_id, finished_goods_stock_id=row.id, package_id=package.id,
            quantity=row.quantity, reserved_by=current.id,
        ))
    log_action(db, current, "reserve", "Package", package.id,
               new_value={"qty": quantity, "sales_order_id": sales_order_id,
                          "stock_ids": [row.id for row in rows]})
    db.commit()
    return {"message": "reserved", "stock_id": stock.id, "package_id": package.id, "quantity": quantity}


@router.post("/reserve")
def reserve(stock_id: int, quantity: int, sales_order_id: int, db: DbSession,
            current: User = Depends(require_permissions("sales.orders", "*"))):
    s = db.get(FinishedGoodsStock, stock_id)
    if not s: raise HTTPException(404, "Stock not found")
    if quantity <= 0: raise HTTPException(400, "Quantity must be > 0")
    package = db.get(Package, s.package_id) if s.package_id else None
    if package and package.manual_receipt_id:
        return _reserve_manual_package(db, current, s, quantity, sales_order_id)
    if quantity > s.available_qty: raise HTTPException(400, "Not enough available")
    s.available_qty -= quantity
    s.reserved_qty += quantity
    if s.available_qty == 0: s.status = "reserved"
    db.add(StockReservation(
        sales_order_id=sales_order_id, finished_goods_stock_id=s.id, package_id=s.package_id,
        quantity=quantity, reserved_by=current.id,
    ))
    log_action(db, current, "reserve", "FinishedGoodsStock", s.id, new_value={"qty": quantity})
    db.commit()
    return {"message": "reserved", "stock_id": s.id, "quantity": quantity}


def _release_manual_package(db, current, package_id, reservation_id):
    package = (
        db.query(Package).filter(Package.id == package_id)
        .with_for_update(of=Package).populate_existing().one()
    )
    if not package.manual_receipt_id or package.status not in {"received_in_storage", "reserved"}:
        raise HTTPException(409, "Only unshipped manual packages can be released")
    stocks = (
        db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package.id)
        .order_by(FinishedGoodsStock.id).with_for_update(of=FinishedGoodsStock)
        .populate_existing().all()
    )
    stock_ids = {stock.id for stock in stocks}
    reservations = (
        db.query(StockReservation).filter(or_(
            StockReservation.package_id == package.id,
            StockReservation.finished_goods_stock_id.in_(stock_ids),
        )).order_by(StockReservation.id).with_for_update(of=StockReservation)
        .populate_existing().all()
    )
    selected = next((row for row in reservations if row.id == reservation_id), None)
    if not selected:
        raise HTTPException(409, "Manual package reservation changed; reload before releasing")
    if db.query(ShipmentPackage.id).join(Shipment).filter(
        ShipmentPackage.package_id == package.id, Shipment.status != "cancelled",
    ).first():
        raise HTTPException(409, "Detach the manual package from its shipment before releasing")
    if any(row.sales_order_id != selected.sales_order_id
           or row.package_id not in (None, package.id)
           or row.finished_goods_stock_id not in stock_ids for row in reservations):
        raise HTTPException(409, "Manual package reservation ownership is inconsistent")
    reserved_by_stock = defaultdict(int)
    for row in reservations:
        reserved_by_stock[row.finished_goods_stock_id] += row.quantity
    if (not stocks or package.total_quantity <= 0
            or sum(stock.quantity for stock in stocks) != package.total_quantity
            or any(stock.sold_qty or stock.available_qty or stock.reserved_qty != stock.quantity
                   or reserved_by_stock[stock.id] != stock.reserved_qty
                   or stock.status not in {"reserved", "available"}
                   for stock in stocks)):
        raise HTTPException(409, "Only a fully reserved, unsold manual package can be released")
    before = [{"id": row.id, "stock_id": row.finished_goods_stock_id, "quantity": row.quantity}
              for row in reservations]
    for stock in stocks:
        stock.available_qty = stock.quantity
        stock.reserved_qty = 0
        stock.status = "available"
    for row in reservations:
        db.delete(row)
    package.status = "received_in_storage"
    log_action(db, current, "release_reservation", "Package", package.id,
               old_value={"sales_order_id": selected.sales_order_id, "reservations": before},
               new_value={"quantity": package.total_quantity, "stock_ids": sorted(stock_ids)})
    db.commit()
    return {"message": "released", "package_id": package.id, "quantity": package.total_quantity}


@router.post("/release-reservation")
def release(reservation_id: int, db: DbSession,
            current: User = Depends(require_permissions("sales.orders", "*"))):
    r = db.get(StockReservation, reservation_id)
    if not r: raise HTTPException(404, "Reservation not found")
    s = db.get(FinishedGoodsStock, r.finished_goods_stock_id)
    # Inspect both links so a historical missing/mismatched package_id cannot
    # send manual stock through the legacy piece-release path.
    package_ids = {pid for pid in (r.package_id, s.package_id if s else None) if pid is not None}
    manual_package = db.query(Package).filter(
        Package.id.in_(package_ids), Package.manual_receipt_id.isnot(None),
    ).first() if package_ids else None
    if manual_package:
        return _release_manual_package(db, current, manual_package.id, reservation_id)
    if s:
        s.available_qty += r.quantity
        s.reserved_qty = max(0, s.reserved_qty - r.quantity)
        s.status = "available"
    db.delete(r)
    log_action(db, current, "release_reservation", "StockReservation", reservation_id)
    db.commit()
    return {"message": "released"}
