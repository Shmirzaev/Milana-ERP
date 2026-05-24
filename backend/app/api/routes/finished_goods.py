from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Brand, FinishedGoodsStock, Model, StockReservation, User
from app.schemas.tracking import FinishedGoodsStockOut
from app.services.audit import log_action
from app.services.finished_goods import repair_missing_brand_metadata

router = APIRouter(prefix="/finished-goods", tags=["finished_goods"])


def _stock_payload(db: DbSession, stock: FinishedGoodsStock) -> dict:
    model = db.get(Model, stock.model_id) if stock.model_id else None
    brand = db.get(Brand, stock.brand_id) if stock.brand_id else None
    return {
        "id": stock.id,
        "production_order_id": stock.production_order_id,
        "sales_order_id": stock.sales_order_id,
        "package_id": stock.package_id,
        "model_id": stock.model_id,
        "model_code": model.code if model else None,
        "model_name": model.name if model else None,
        "brand_id": stock.brand_id,
        "brand_name": brand.name if brand else None,
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
    qry = db.query(FinishedGoodsStock)
    if model_id: qry = qry.filter(FinishedGoodsStock.model_id == model_id)
    if status: qry = qry.filter(FinishedGoodsStock.status == status)
    if brand_id: qry = qry.filter(FinishedGoodsStock.brand_id == brand_id)
    return [_stock_payload(db, row) for row in qry.order_by(FinishedGoodsStock.id.desc()).all()]


@router.get("/branded-stock", response_model=list[FinishedGoodsStockOut])
def list_branded(db: DbSession, _: CurrentUser):
    repaired = repair_missing_brand_metadata(db)
    if repaired:
        db.commit()
    rows = db.query(FinishedGoodsStock).filter(
        FinishedGoodsStock.brand_id.isnot(None),
        FinishedGoodsStock.available_qty > 0,
    ).order_by(FinishedGoodsStock.id.desc()).all()
    return [_stock_payload(db, row) for row in rows]


@router.post("/reserve")
def reserve(stock_id: int, quantity: int, sales_order_id: int, db: DbSession,
            current: User = Depends(require_permissions("sales.orders", "*"))):
    s = db.get(FinishedGoodsStock, stock_id)
    if not s: raise HTTPException(404, "Stock not found")
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
