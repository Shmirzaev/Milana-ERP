import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends
from fastapi import UploadFile, File
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.config import settings
from app.models import (
    SalesOrder, SalesOrderItem, FinishedGoodsStock, StockReservation,
    Customer, Model, User, ProductionOrder, Shipment, Task, Department, Invoice,
)
from app.schemas.sales import (
    SalesOrderIn, SalesOrderUpdate, SalesOrderOut, SalesOrderDetail,
)
from app.services.audit import log_action
from app.services.finished_goods import repair_missing_brand_metadata
from app.services.numbering import next_sales_order_no
from app.services.numbering import next_invoice_no
from app.services.workflow import notify_department

router = APIRouter(prefix="/sales-orders", tags=["sales"])


def _serialize_sales_order(
    db: DbSession,
    so: SalesOrder,
    *,
    include_items: bool = False,
) -> dict:
    """Shape sales-order payloads with customer/model names for frontend display."""
    schema_cls = SalesOrderDetail if include_items else SalesOrderOut
    payload = schema_cls.model_validate(so).model_dump()

    customer = db.get(Customer, so.customer_id) if so.customer_id else None
    if customer:
        payload["customer_name"] = customer.name
        payload["customer"] = {"id": customer.id, "name": customer.name}
    else:
        payload["customer_name"] = None
        payload["customer"] = None

    if include_items:
        model_ids = {int(item.model_id) for item in (so.items or []) if item.model_id}
        model_rows = (
            db.query(Model.id, Model.code, Model.name, Model.details_json)
            .filter(Model.id.in_(model_ids))
            .all()
            if model_ids
            else []
        )
        model_map = {
            int(mid): {
                "id": int(mid),
                "code": code,
                "name": name,
                "translations": (details or {}).get("translation") if isinstance(details, dict) else None,
            }
            for mid, code, name, details in model_rows
        }
        for item in payload.get("items", []):
            model_ref = model_map.get(int(item.get("model_id") or 0))
            item["model_code"] = model_ref["code"] if model_ref else None
            item["model_name"] = model_ref["name"] if model_ref else None
            item["model"] = model_ref

    return payload


def _is_any_stock_token(value: str | None) -> bool:
    token = str(value or "").strip().lower()
    return token in {"", "*", "any", "mixed", "__any__", "pack60", "bag"}


def _stock_variant_key(model_id: int, color: str, size: str, brand_id: int | None) -> tuple[int, str, str, int | None]:
    return (int(model_id), str(color or "").strip(), str(size or "").strip(), brand_id)


def _stock_rows_for_variant(
    db: DbSession,
    *,
    model_id: int,
    color: str,
    size: str,
    brand_id: int | None,
) -> list[FinishedGoodsStock]:
    qry = db.query(FinishedGoodsStock).filter(
        FinishedGoodsStock.model_id == model_id,
        FinishedGoodsStock.status == "available",
        FinishedGoodsStock.available_qty > 0,
    )
    if not _is_any_stock_token(color):
        qry = qry.filter(FinishedGoodsStock.color == color)
    if not _is_any_stock_token(size):
        qry = qry.filter(FinishedGoodsStock.size == size)
    if brand_id is not None:
        qry = qry.filter(FinishedGoodsStock.brand_id == brand_id)
    return qry.order_by(FinishedGoodsStock.id.asc()).all()


def _notify_planning_shortage(
    db: DbSession,
    *,
    so: SalesOrder,
    current: User,
    shortages: list[dict],
) -> None:
    if not shortages:
        return
    planning_dept = db.query(Department).filter(Department.code == "PLN").first()
    planning_user = (
        db.query(User)
        .filter(User.is_active.is_(True), User.department_id == planning_dept.id if planning_dept else False)
        .order_by(User.id.asc())
        .first()
        if planning_dept
        else None
    )
    if planning_user:
        summary = ", ".join(f"M{r['model_id']} {r['color']}/{r['size']}: {r['shortage']}" for r in shortages[:6])
        if len(shortages) > 6:
            summary += f" (+{len(shortages) - 6} more)"
        db.add(
            Task(
                title=f"Stock shortage for {so.order_no}",
                description=f"Auto-created from reserve-stock. Resolve shortages: {summary}",
                assigned_to=planning_user.id,
                created_by=current.id,
                status="pending",
                priority="high",
                due_date=so.deadline,
            )
        )
    notify_department(
        db,
        department_code="PLN",
        title=f"Shortage detected for {so.order_no}",
        message=f"{len(shortages)} shortage line(s) were detected during reserve-stock.",
        link=f"/sales-orders/{so.id}",
        exclude_user_id=current.id,
    )


def _reserve_branded_stock(
    db: DbSession,
    *,
    so: SalesOrder,
    current: User,
    lines: list[SalesOrderItem] | None = None,
    fail_on_shortage: bool = False,
    notify_shortage: bool = True,
    notify_storage_when_ready: bool = False,
) -> tuple[list[dict], list[dict]]:
    repair_missing_brand_metadata(db)
    line_rows = lines if lines is not None else db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == so.id).all()
    requested_by_variant: dict[tuple[int, str, str, int | None], int] = defaultdict(int)
    for line in line_rows:
        key = _stock_variant_key(line.model_id, line.color, line.size, line.brand_id)
        requested_by_variant[key] += int(line.quantity or 0)

    existing_rows = (
        db.query(StockReservation, FinishedGoodsStock)
        .join(FinishedGoodsStock, FinishedGoodsStock.id == StockReservation.finished_goods_stock_id)
        .filter(StockReservation.sales_order_id == so.id)
        .all()
    )

    outstanding_by_variant: dict[tuple[int, str, str, int | None], int] = {}
    for key, requested_qty in requested_by_variant.items():
        model_id, color, size, brand_id = key
        any_color = _is_any_stock_token(color)
        any_size = _is_any_stock_token(size)
        already_reserved = 0
        for reservation, stock in existing_rows:
            if int(stock.model_id) != int(model_id):
                continue
            if not any_color and str(stock.color or "").strip() != color:
                continue
            if not any_size and str(stock.size or "").strip() != size:
                continue
            if brand_id is not None and int(stock.brand_id or 0) != int(brand_id):
                continue
            already_reserved += int(reservation.quantity or 0)
        outstanding_by_variant[key] = max(0, int(requested_qty) - already_reserved)

    if requested_by_variant and all(qty <= 0 for qty in outstanding_by_variant.values()):
        raise HTTPException(409, "Stock has already been fully reserved for this sales order")

    shortages_precheck: list[dict] = []
    for (model_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        available_qty = sum(
            int(row.available_qty or 0)
            for row in _stock_rows_for_variant(
                db,
                model_id=model_id,
                color=color,
                size=size,
                brand_id=brand_id,
            )
        )
        if available_qty < requested_qty:
            shortages_precheck.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "requested": requested_qty,
                    "available": available_qty,
                    "shortage": requested_qty - available_qty,
                }
            )

    if fail_on_shortage and shortages_precheck:
        summary = "; ".join(
            f"M{s['model_id']} {s['color']}/{s['size']} need {s['requested']}, available {s['available']}"
            for s in shortages_precheck[:4]
        )
        if len(shortages_precheck) > 4:
            summary += f" (+{len(shortages_precheck) - 4} more)"
        raise HTTPException(409, f"Not enough branded stock to fulfill this order: {summary}")

    reservations: list[dict] = []
    shortages: list[dict] = []
    for (model_id, color, size, brand_id), requested_qty in outstanding_by_variant.items():
        if requested_qty <= 0:
            continue
        needed = int(requested_qty)
        stocks = _stock_rows_for_variant(
            db,
            model_id=model_id,
            color=color,
            size=size,
            brand_id=brand_id,
        )
        for s in stocks:
            if needed <= 0:
                break
            take = min(needed, int(s.available_qty or 0))
            if take <= 0:
                continue
            s.available_qty = int(s.available_qty or 0) - take
            s.reserved_qty = int(s.reserved_qty or 0) + take
            if int(s.available_qty or 0) == 0:
                s.status = "reserved"
            db.add(
                StockReservation(
                    sales_order_id=so.id,
                    finished_goods_stock_id=s.id,
                    package_id=s.package_id,
                    quantity=take,
                    reserved_by=current.id,
                )
            )
            reservations.append({"stock_id": s.id, "qty": take})
            needed -= take
        if needed > 0:
            shortages.append(
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": color,
                    "size": size,
                    "shortage": needed,
                }
            )

    if not shortages and reservations:
        so.status = "ready"
        auto_note = "[Auto route] Branded stock reserved and sent to storage team for shipment prep."
        so.notes = f"{so.notes}\n{auto_note}".strip() if so.notes else auto_note
        if notify_storage_when_ready:
            notify_department(
                db,
                department_code="FGS",
                title=f"{so.order_no} ready for shipment prep",
                message="Branded stock order has been auto-reserved. Prepare shipment from ready-goods storage.",
                link=f"/sales-orders/{so.id}",
                exclude_user_id=current.id,
            )

    if shortages and notify_shortage:
        _notify_planning_shortage(db, so=so, current=current, shortages=shortages)

    return reservations, shortages


@router.post("/printing-attachments/upload", status_code=201)
async def upload_printing_attachment(
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("sales.orders", "*")),
):
    _ = current
    ext = Path(file.filename or "").suffix.lower()
    os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
    safe_name = f"so_print_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.SALES_ORDER_FILES_DIR, safe_name)
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(400, "Empty file")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 20MB)")
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/sales-order-files/{safe_name}"
    return {
        "file_url": file_url,
        "file_name": file.filename or safe_name,
        "content_type": file.content_type,
    }


@router.get("")
def list_sales_orders(
    db: DbSession, _: CurrentUser,
    status: str | None = None, order_type: str | None = None,
    customer_id: int | None = None, q: str | None = None,
    page: int = 1, page_size: int = 50,
    include_total: bool = False,
):
    qry = db.query(SalesOrder)
    if status: qry = qry.filter(SalesOrder.status == status)
    if order_type: qry = qry.filter(SalesOrder.order_type == order_type)
    if customer_id: qry = qry.filter(SalesOrder.customer_id == customer_id)
    if q: qry = qry.filter(SalesOrder.order_no.ilike(f"%{q}%"))
    total = qry.count() if include_total else 0
    safe_page = max(1, page)
    safe_size = max(1, min(page_size, 500))
    rows = qry.order_by(SalesOrder.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size).all()
    payload = [_serialize_sales_order(db, so, include_items=False) for so in rows]
    if include_total:
        return {"rows": payload, "total": total, "page": safe_page, "page_size": safe_size}
    return payload


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
        printing_instructions=payload.printing_instructions,
        printing_attachments=[a.model_dump() for a in payload.printing_attachments] if payload.printing_attachments else [],
        notes=payload.notes,
        created_by=current.id,
    )
    db.add(so); db.flush()
    total = 0.0
    created_lines: list[SalesOrderItem] = []
    for item in payload.items:
        if not db.get(Model, item.model_id):
            raise HTTPException(404, f"Model {item.model_id} not found")
        line = SalesOrderItem(sales_order_id=so.id, **item.model_dump())
        db.add(line)
        created_lines.append(line)
        total += float(item.unit_price) * item.quantity
    so.total_amount = total
    if payload.order_type == "branded_stock_sale":
        reservations, shortages = _reserve_branded_stock(
            db,
            so=so,
            current=current,
            lines=created_lines,
            fail_on_shortage=True,
            notify_shortage=False,
            notify_storage_when_ready=True,
        )
        log_action(
            db,
            current,
            "reserve_stock_auto",
            "SalesOrder",
            so.id,
            new_value={"reservations": reservations, "shortages": shortages},
        )
    log_action(db, current, "create", "SalesOrder", so.id, new_value={"order_no": so.order_no})
    db.commit(); db.refresh(so)
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == so.id).first()
    return _serialize_sales_order(db, so, include_items=True)


@router.get("/{sid}", response_model=SalesOrderDetail)
def get_sales_order(sid: int, db: DbSession, _: CurrentUser):
    so = db.query(SalesOrder).options(joinedload(SalesOrder.items)).filter(SalesOrder.id == sid).first()
    if not so: raise HTTPException(404, "Sales order not found")
    return _serialize_sales_order(db, so, include_items=True)


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
    notify_department(
        db,
        department_code="PLN",
        title=f"Sales order {so.order_no} sent to planning",
        message="Planning should calculate material usage, estimated cost, and lead time.",
        link=f"/planning?so_id={so.id}",
        exclude_user_id=current.id,
    )
    log_action(db, current, "confirm", "SalesOrder", so.id)
    db.commit(); db.refresh(so)
    return so


@router.post("/{sid}/approve-planning", response_model=SalesOrderOut)
def approve_planning_estimate(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.order_type != "client_order":
        raise HTTPException(400, "Planning approval flow is only for client_order")
    if so.status != "pending_sales_approval":
        raise HTTPException(400, f"Cannot approve planning estimate in status '{so.status}'")

    so.status = "planning_approved"
    note = "[Sales approval] Planning estimate approved. Returned to planning for PO creation."
    so.notes = f"{so.notes}\n{note}".strip() if so.notes else note

    notify_department(
        db,
        department_code="PLN",
        title=f"Planning estimate approved for {so.order_no}",
        message="Sales approved the estimate. Create the production order now.",
        link=f"/planning?so_id={so.id}",
        exclude_user_id=current.id,
    )
    log_action(db, current, "approve_planning", "SalesOrder", so.id)
    db.commit()
    db.refresh(so)
    return so


@router.post("/{sid}/reserve-stock")
def reserve_stock(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    """For branded_stock_sale: try to reserve from FinishedGoodsStock for each line."""
    so = db.get(SalesOrder, sid)
    if not so: raise HTTPException(404, "Sales order not found")
    if so.order_type != "branded_stock_sale":
        raise HTTPException(400, "Reservation only applies to branded stock sales")

    reservations, shortages = _reserve_branded_stock(
        db,
        so=so,
        current=current,
        fail_on_shortage=False,
        notify_shortage=True,
        notify_storage_when_ready=True,
    )
    log_action(db, current, "reserve_stock", "SalesOrder", so.id, new_value={"reservations": reservations, "shortages": shortages})
    db.commit()
    return {"reservations": reservations, "shortages": shortages}


@router.post("/{sid}/generate-invoice")
def generate_invoice_for_order(
    sid: int,
    db: DbSession,
    current: User = Depends(require_permissions("finance.invoice", "sales.orders", "*")),
):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")
    allowed = {"confirmed", "in_production", "cutting", "sewing", "packaging", "storage", "ready", "reserved", "shipped", "delivered", "planning", "planning_approved", "production"}
    if str(so.status or "") not in allowed:
        raise HTTPException(400, f"Cannot generate invoice for order in status '{so.status}'")
    existing = db.query(Invoice).filter(Invoice.sales_order_id == sid).order_by(Invoice.id.desc()).first()
    if existing:
        return {
            "id": existing.id,
            "sales_order_id": existing.sales_order_id,
            "invoice_no": existing.invoice_no,
            "amount": float(existing.amount or 0),
            "status": existing.status,
            "issued_at": existing.issued_at,
            "due_date": existing.due_date,
            "created_existing": True,
        }
    inv = Invoice(
        sales_order_id=sid,
        invoice_no=next_invoice_no(db),
        amount=float(so.total_amount or 0),
        status="unpaid",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.flush()
    log_action(db, current, "generate_invoice", "Invoice", inv.id, new_value={"sales_order_id": sid, "amount": float(inv.amount or 0)})
    db.commit()
    db.refresh(inv)
    return {
        "id": inv.id,
        "sales_order_id": inv.sales_order_id,
        "invoice_no": inv.invoice_no,
        "amount": float(inv.amount or 0),
        "status": inv.status,
        "issued_at": inv.issued_at,
        "due_date": inv.due_date,
        "created_existing": False,
    }


@router.delete("/{sid}", status_code=204)
def delete_sales_order(sid: int, db: DbSession, current: User = Depends(require_permissions("sales.orders", "*"))):
    so = db.get(SalesOrder, sid)
    if not so:
        raise HTTPException(404, "Sales order not found")

    if so.status not in ("draft", "cancelled"):
        raise HTTPException(409, "Only draft or cancelled sales orders can be deleted")
    if db.query(ProductionOrder).filter(ProductionOrder.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked production orders")
    if db.query(Shipment).filter(Shipment.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has linked shipments")
    if db.query(StockReservation).filter(StockReservation.sales_order_id == sid).first():
        raise HTTPException(409, "Sales order already has stock reservations")

    db.delete(so)
    log_action(db, current, "delete", "SalesOrder", sid, new_value={"order_no": so.order_no})
    db.commit()
