from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    SalesOrder, SalesOrderItem, FinishedGoodsStock, StockReservation,
    Customer, Model, User,
)
from app.schemas.sales import (
    SalesOrderIn, SalesOrderUpdate, SalesOrderOut, SalesOrderDetail,
)
from app.services.audit import log_action
from app.services.numbering import next_sales_order_no

router = APIRouter(prefix="/sales-orders", tags=["sales"])


@router.get("", response_model=list[SalesOrderOut])
def list_sales_orders(
    db: DbSession, _: CurrentUser,
    status: str | None = None, order_type: str | None = None,
    customer_id: int | None = None, q: str | None = None,
    page: int = 1, page_size: int = 50,
):
    qry = db.query(SalesOrder)
    if status: qry = qry.filter(SalesOrder.status == status)
    if order_type: qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id: qry = qry.filter(SalesOrder.customer_id == customer_id)
    if q: qry = qry.filter(SalesOrder.order_no.ilike(f"%{q}%"))
    return qry.order_by(SalesOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.post("", response_model=SalesOrderDetail, status_code=201)
def create_sales_order(payload: SalesOrderIn, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    if payload.order_type not in ("client_order", "branded_stock_sale"):
        raise HTTPException(400, "Invalid order_type")
    if payload.customer_id and not db.get(Customer, payload.customer_id):
        raise HTTPException(404, "Customer not found")
    so = SalesOrder(
        order_no=next_sales_order_no(db),
        customer_id=payload.customer_id,
        order_type=payload.order_type,
        status="draft",
        deadline=payload.deadline,
        notes=payload.notes,
        created_by=current.id,
    )
    db.add(so); db.flush()
    total = 0.0
    for item in payload.items:
        if not db.get(Model, item.model_id):
            raise HTTPException(404, f"Model {item.model_id} not found")
        line = SalesOrderItem(sales_order_id=so.id, **item.model_dump())
        db.add(line)
        total += float(item.unit_price) * item.quantity
    so.total_amount = total
    log_action(db, current, "create", "SalesOrder", so.id, new_value={"order_no": so.order_no})
    db.commit(); db.refresh(so)
    return so


@router.get("/{sid}", response_model=SalesOrderDetail)
def get_sales_order(sid: int, db: DbSession, _: CurrentUser):
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == sid).first()
    if not so: raise HTTPException(404, "Sales order not found")
    return so


@router.patch("/{sid}", response_model=SalesOrderOut)
def update_sales_order(sid: int, payload: SalesOrderUpdate, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(so, k, v)
    log_action(db, current, "update", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return so


@router.post("/{sid}/confirm", response_model=SalesOrderOut)
def confirm_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.status != "draft":
        raise HTTPException(400, f"Cannot confirm order in status '{so.status}'")
    so.status = "confirmed"
    log_action(db, current, "confirm", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return so


@router.post("/{sid}/reserve-stock")
def reserve_stock(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.order_type != "branded_stock_sale":
        raise HTTPException(400, "Reservation only applies to branded stock sales")

    reservations, shortages = [], []
    for line in so.items:
        needed = line.quantity
        stocks = db.query(FinishedGoodsStock).filter(
            FinishedGoodsStock.model_id == line.model_id,
            FinishedGoodsStock.color == line.color,
            FinishedGoodsStock.size == line.size,
            FinishedGoodsStock.status == "available",
            FinishedGoodsStock.available_qty > 0,
        ).all()
        for s in stocks:
            if needed <= 0: break
            take = min(needed, s.available_qty)
            s.available_qty -= take
            s.reserved_qty += take
            if s.available_qty == 0:
                s.status = "reserved"
            r = StockReservation(
                sales_order_id=so.id,
                finished_goods_stock_id=s.id,
                package_id=s.package_id,
                quantity=take,
                reserved_by=current.id,
            )
            db.add(r)
            reservations.append({"stock_id": s.id, "qty": take})
            needed -= take
        if needed > 0:
            shortages.append({
                "model_id": line.model_id, "color": line.color, "size": line.size, "shortage": needed,
            })
    log_action(db, current, "reserve_stock", "SalesOrder", so.id, new_value={"reservations": reservations, "shortages": shortages})
    db.commit()
    return {"reservations": reservations, "shortages": shortages}
