from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Brand, FinishedGoodsStock, Model, Package, ProductionOrder, StockReservation, User
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


@router.post("/reserve")
def reserve(stock_id: int, quantity: int, sales_order_id: int, db: DbSession,
            current: User = Depends(require_permissions("sales.orders", "*"))):
    s = db.get(FinishedGoodsStock, stock_id)
    if not s: raise HTTPException(404, "Stock not found")
    if quantity <= 0: raise HTTPException(400, "Quantity must be > 0")
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


@router.post("/release-reservation")
def release(reservation_id: int, db: DbSession,
            current: User = Depends(require_permissions("sales.orders", "*"))):
    r = db.get(StockReservation, reservation_id)
    if not r: raise HTTPException(404, "Reservation not found")
    s = db.get(FinishedGoodsStock, r.finished_goods_stock_id)
    if s:
        s.available_qty += r.quantity
        s.reserved_qty = max(0, s.reserved_qty - r.quantity)
        s.status = "available"
    db.delete(r)
    log_action(db, current, "release_reservation", "StockReservation", reservation_id)
    db.commit()
    return {"message": "released"}
