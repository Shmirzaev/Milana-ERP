from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Department,
    FinishedGoodsStock,
    Invoice,
    Item,
    ModelBOM,
    Notification,
    Package,
    ProductionOrder,
    SalesOrder,
    StockBatch,
    StockMovement,
    User,
    WasteRecord,
    WorkOrder,
)
from app.services.numbering import next_invoice_no

WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]


def _work_orders_by_op(db: Session, production_order_id: int) -> dict[str, WorkOrder]:
    rows = db.query(WorkOrder).filter(WorkOrder.production_order_id == production_order_id).all()
    return {w.operation: w for w in rows}


def _next_existing_operation(operation: str, by_op: dict[str, WorkOrder]) -> str | None:
    """Find the next stage that actually exists on this PO.

    Some orders intentionally skip printing. In that case cutting should
    advance directly to sewing instead of stalling on a missing printing WO.
    """
    try:
        idx = WORKFLOW_SEQUENCE.index(operation)
    except ValueError:
        return None
    for candidate in WORKFLOW_SEQUENCE[idx + 1 :]:
        if candidate in by_op:
            return candidate
    return None


def _start_if_waiting(wo: WorkOrder) -> None:
    if wo.status in ("new", "planning", "waiting"):
        wo.status = "in_progress"
        if not wo.start_time:
            wo.start_time = datetime.now(timezone.utc)


def _complete_if_done(wo: WorkOrder) -> None:
    planned = int(wo.planned_output_qty or 0)
    passed = int(wo.passed_qty or 0)
    if planned > 0 and passed >= planned and wo.status != "completed":
        wo.status = "completed"
        wo.end_time = datetime.now(timezone.utc)


def sync_production_order_status(db: Session, production_order_id: int) -> None:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        return
    by_op = _work_orders_by_op(db, production_order_id)
    ordered = [by_op[op] for op in WORKFLOW_SEQUENCE if op in by_op]
    if not ordered:
        po.status = "planning"
        return

    first_active = next((w for w in ordered if w.status != "completed"), None)
    if first_active is None:
        po.status = "finished_storage"
        return
    po.status = first_active.operation


def advance_workflow(
    db: Session,
    wo: WorkOrder,
    *,
    trigger_output_qty: int = 0,
    allow_next_stage_start: bool = True,
) -> None:
    _start_if_waiting(wo)
    _complete_if_done(wo)

    if allow_next_stage_start and trigger_output_qty > 0:
        by_op = _work_orders_by_op(db, wo.production_order_id)
        next_op = _next_existing_operation(wo.operation, by_op)
        if next_op:
            nxt = by_op.get(next_op)
            if nxt:
                _start_if_waiting(nxt)

    sync_production_order_status(db, wo.production_order_id)


def notify_department(
    db: Session,
    *,
    department_code: str,
    title: str,
    message: str | None = None,
    exclude_user_id: int | None = None,
) -> int:
    dept = db.query(Department).filter(Department.code == department_code).first()
    if not dept:
        return 0
    users = db.query(User).filter(User.department_id == dept.id, User.is_active.is_(True)).all()
    created = 0
    for u in users:
        if exclude_user_id and u.id == exclude_user_id:
            continue
        db.add(Notification(user_id=u.id, title=title, message=message))
        created += 1
    return created


def consume_stock_batch(
    db: Session,
    *,
    batch_id: int,
    quantity: float,
    unit: str,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
) -> None:
    if quantity <= 0:
        return
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(404, f"Stock batch {batch_id} not found")
    available = float(batch.quantity or 0)
    if available < quantity:
        raise HTTPException(
            409,
            f"Insufficient stock in batch {batch.batch_no}: available {available}, requested {quantity}",
        )
    batch.quantity = available - quantity
    db.add(
        StockMovement(
            movement_type="consume",
            item_id=batch.item_id,
            batch_id=batch.id,
            from_warehouse_id=batch.warehouse_id,
            to_warehouse_id=None,
            quantity=quantity,
            unit=unit or batch.unit,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=user_id,
        )
    )


def consume_item_from_batches(
    db: Session,
    *,
    item_id: int,
    quantity: float,
    unit: str,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
) -> float:
    if quantity <= 0:
        return 0.0
    left = float(quantity)
    consumed = 0.0
    batches = (
        db.query(StockBatch)
        .filter(StockBatch.item_id == item_id, StockBatch.quantity > 0)
        .order_by(StockBatch.received_date.asc(), StockBatch.id.asc())
        .all()
    )
    for b in batches:
        if left <= 0:
            break
        take = min(left, float(b.quantity or 0))
        if take <= 0:
            continue
        b.quantity = float(b.quantity or 0) - take
        db.add(
            StockMovement(
                movement_type="consume",
                item_id=item_id,
                batch_id=b.id,
                from_warehouse_id=b.warehouse_id,
                to_warehouse_id=None,
                quantity=take,
                unit=unit or b.unit,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=user_id,
            )
        )
        consumed += take
        left -= take

    if consumed <= 0:
        # Keep movement ledger complete even when no batch rows are available.
        db.add(
            StockMovement(
                movement_type="consume",
                item_id=item_id,
                batch_id=None,
                from_warehouse_id=None,
                to_warehouse_id=None,
                quantity=quantity,
                unit=unit,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=user_id,
            )
        )
        consumed = quantity
    return consumed


def consume_packaging_materials_from_bom(
    db: Session,
    *,
    production_order_id: int,
    packed_qty: int,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
) -> None:
    if packed_qty <= 0:
        return
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        return
    bom_rows = db.query(ModelBOM).filter(ModelBOM.model_id == po.model_id).all()
    if not bom_rows:
        return
    for row in bom_rows:
        item = db.get(Item, row.item_id)
        if not item or item.category != "packaging":
            continue
        qty = float(row.quantity_per_piece) * packed_qty * (1.0 + float(row.waste_percent or 0) / 100.0)
        consume_item_from_batches(
            db,
            item_id=item.id,
            quantity=qty,
            unit=row.unit or item.unit,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
        )


def create_waste_record(
    db: Session,
    *,
    production_order_id: int | None,
    work_order_id: int | None,
    source_department_id: int | None,
    item_id: int | None,
    batch_id: int | None,
    waste_type: str,
    quantity: float,
    unit: str,
    reason: str | None,
    created_by: int | None,
) -> WasteRecord | None:
    if quantity <= 0:
        return None
    rec = WasteRecord(
        production_order_id=production_order_id,
        work_order_id=work_order_id,
        source_department_id=source_department_id,
        item_id=item_id,
        batch_id=batch_id,
        waste_type=waste_type,
        quantity=quantity,
        unit=unit,
        reason=reason,
        sellable=False,
        estimated_value=0,
        status="recorded",
        created_by=created_by,
    )
    db.add(rec)
    return rec


def decrement_finished_goods_for_package(db: Session, package: Package) -> None:
    rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package.id).all()
    for s in rows:
        total_available = int(s.available_qty or 0) + int(s.reserved_qty or 0)
        shipped = min(int(s.quantity or 0), total_available)
        if shipped <= 0:
            continue
        take_available = min(int(s.available_qty or 0), shipped)
        left = shipped - take_available
        s.available_qty = int(s.available_qty or 0) - take_available
        if left > 0:
            s.reserved_qty = max(0, int(s.reserved_qty or 0) - left)
        s.sold_qty = int(s.sold_qty or 0) + shipped
        if s.available_qty <= 0 and s.reserved_qty <= 0:
            s.status = "sold"


def ensure_invoice_for_delivered_shipment(
    db: Session,
    *,
    sales_order_id: int | None,
) -> Invoice | None:
    if not sales_order_id:
        return None
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return None
    existing = db.query(Invoice).filter(Invoice.sales_order_id == sales_order_id).first()
    if existing:
        return existing
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=14)
    inv = Invoice(
        sales_order_id=sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=float(so.total_amount or 0),
        status="unpaid",
        issued_at=now,
        due_date=due,
    )
    db.add(inv)
    return inv
