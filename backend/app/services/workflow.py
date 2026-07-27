from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, lazyload

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
    Bundle,
    CuttingRecord,
    SewingReplacementRequest,
)
from app.services.numbering import next_invoice_no

WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
_OP_INDEX = {op: idx for idx, op in enumerate(WORKFLOW_SEQUENCE)}
_STARTED_WORK_ORDER_STATUSES = {"in_progress", "pending", "collected", "ready"}


def _work_orders_by_op(
    db: Session,
    production_order_id: int,
    production_batch_id: int | None = None,
) -> dict[str, WorkOrder]:
    qry = db.query(WorkOrder).filter(WorkOrder.production_order_id == production_order_id)
    if production_batch_id is None:
        qry = qry.filter(WorkOrder.production_batch_id.is_(None))
    else:
        qry = qry.filter(WorkOrder.production_batch_id == production_batch_id)
    rows = qry.all()
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


def _queue_printing_if_waiting(wo: WorkOrder) -> None:
    """Printing starts in a pending queue until master collects it."""
    if wo.operation == "printing" and wo.status in ("new", "planning", "waiting"):
        wo.status = "pending"


def _upstream_failed_qty(db: Session, wo: WorkOrder) -> int:
    op_index = _OP_INDEX.get(str(wo.operation), -1)
    if op_index <= 0:
        return 0
    prior_operations = WORKFLOW_SEQUENCE[:op_index]
    # Sewing failures are replacement demand, not accepted production loss.
    # They must not make packaging or storage appear complete while the
    # replacement pieces are still moving through cutting and sewing.
    if "sewing" in prior_operations:
        prior_operations = [operation for operation in prior_operations if operation != "sewing"]
    qry = (
        db.query(func.coalesce(func.sum(WorkOrder.failed_qty), 0))
        .filter(
            WorkOrder.production_order_id == wo.production_order_id,
            WorkOrder.operation.in_(prior_operations),
        )
    )
    if wo.production_batch_id is None:
        qry = qry.filter(WorkOrder.production_batch_id.is_(None))
    else:
        qry = qry.filter(WorkOrder.production_batch_id == wo.production_batch_id)
    return int(qry.scalar() or 0)


def processed_work_order_qty(db: Session, wo: WorkOrder) -> int:
    planned = max(0, int(wo.planned_output_qty or 0))
    own_failed = 0 if wo.operation == "sewing" else int(wo.failed_qty or 0)
    processed = int(wo.passed_qty or 0) + own_failed + _upstream_failed_qty(db, wo)
    return min(planned, processed) if planned > 0 else max(0, processed)


def _complete_if_done(db: Session, wo: WorkOrder) -> None:
    replacement_qry = db.query(SewingReplacementRequest.id).filter(
        SewingReplacementRequest.production_order_id == wo.production_order_id,
    )
    if wo.production_batch_id is not None:
        replacement_qry = replacement_qry.filter(
            SewingReplacementRequest.production_batch_id == wo.production_batch_id,
        )
    if wo.operation == "cutting":
        replacement_qry = replacement_qry.filter(
            SewingReplacementRequest.cut_qty < SewingReplacementRequest.requested_qty,
        )
    elif wo.operation in {"sewing", "packaging", "storage_transfer"}:
        replacement_qry = replacement_qry.filter(
            SewingReplacementRequest.replaced_qty < SewingReplacementRequest.requested_qty,
        )
    else:
        replacement_qry = replacement_qry.filter(False)
    if replacement_qry.first():
        return
    planned = int(wo.planned_output_qty or 0)
    processed = processed_work_order_qty(db, wo)
    if planned > 0 and processed >= planned and wo.status != "completed":
        wo.status = "completed"
        wo.end_time = datetime.now(timezone.utc)


def _work_order_has_started(wo: WorkOrder) -> bool:
    if wo.operation == "storage_transfer":
        for value in (wo.actual_output_qty, wo.passed_qty, wo.failed_qty, wo.rework_qty):
            try:
                if int(value or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False
    if str(wo.status or "") in _STARTED_WORK_ORDER_STATUSES:
        return True
    for value in (wo.actual_input_qty, wo.actual_output_qty, wo.passed_qty, wo.failed_qty, wo.rework_qty):
        try:
            if int(value or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def propagate_cutting_plan_from_output(db: Session, wo: WorkOrder) -> None:
    """Raise downstream work plans when cutting creates more pieces than planned."""
    if wo.operation != "cutting":
        return

    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        return

    db.flush()
    bundle_qry = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == wo.production_order_id,
    )
    if wo.production_batch_id is not None:
        bundle_qry = bundle_qry.filter(Bundle.production_batch_id == wo.production_batch_id)

    replacement_cut_qty = int(
        db.query(func.coalesce(func.sum(SewingReplacementRequest.cut_qty), 0))
        .filter(SewingReplacementRequest.cutting_work_order_id == wo.id)
        .scalar()
        or 0
    )
    output_qty = max(
        0,
        int(wo.actual_output_qty or 0) - replacement_cut_qty,
        int(wo.passed_qty or 0) - replacement_cut_qty,
        int(
            db.query(func.coalesce(func.sum(CuttingRecord.total_bundled_quantity), 0))
            .filter(CuttingRecord.work_order_id == wo.id)
            .scalar()
            or 0
        ) - replacement_cut_qty,
        int(bundle_qry.scalar() or 0) - replacement_cut_qty,
    )
    if output_qty <= 0:
        return

    downstream_ops = WORKFLOW_SEQUENCE[WORKFLOW_SEQUENCE.index("cutting") + 1 :]
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == wo.production_order_id,
        WorkOrder.operation.in_(downstream_ops),
    )
    if wo.production_batch_id is None:
        qry = qry.filter(WorkOrder.production_batch_id.is_(None))
    else:
        qry = qry.filter(WorkOrder.production_batch_id == wo.production_batch_id)

    for row in qry.all():
        if int(row.planned_input_qty or 0) < output_qty:
            row.planned_input_qty = output_qty
        if int(row.planned_output_qty or 0) < output_qty:
            row.planned_output_qty = output_qty


def sync_production_order_status(db: Session, production_order_id: int) -> None:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        return
    all_wos = db.query(WorkOrder).filter(WorkOrder.production_order_id == production_order_id).all()
    if not all_wos:
        po.status = "planning"
        return

    active = [w for w in all_wos if w.status not in ("completed", "rejected", "cancelled")]
    if not active:
        po.status = "finished_storage"
        return
    started = [w for w in active if _work_order_has_started(w)]
    if started:
        current = max(started, key=lambda w: (_OP_INDEX.get(w.operation, -1), w.id))
    else:
        current = min(active, key=lambda w: (_OP_INDEX.get(w.operation, 999), w.id))
    po.status = current.operation


def sync_storage_transfer_work_order(db: Session, production_order_id: int) -> None:
    """Recalculate storage_transfer WO counters from package state.

    Storage transfer progress is driven by package intake at FGS.
    When packages move to received/reserved/shipped/delivered, this WO should
    advance even if no manual WO record was posted.
    """
    # SessionLocal uses autoflush=False, so persist any pending package status
    # changes before we aggregate moved quantities.
    db.flush()

    wo = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "storage_transfer",
            WorkOrder.production_batch_id.is_(None),
        )
        .order_by(WorkOrder.id.asc())
        .first()
    )
    if not wo:
        return

    moved_total = int(
        db.query(func.coalesce(func.sum(Package.total_quantity), 0))
        .filter(
            Package.production_order_id == production_order_id,
            Package.status.in_(["received_in_storage", "reserved", "shipped", "delivered"]),
        )
        .scalar()
        or 0
    )
    planned = max(0, int(wo.planned_output_qty or 0))
    passed = moved_total if planned <= 0 else min(moved_total, planned)
    upstream_failed = _upstream_failed_qty(db, wo) if planned > 0 else 0
    processed = passed + min(upstream_failed, max(0, planned - passed)) if planned > 0 else passed
    has_open_replacements = bool(
        db.query(SewingReplacementRequest.id)
        .filter(
            SewingReplacementRequest.production_order_id == production_order_id,
            SewingReplacementRequest.replaced_qty < SewingReplacementRequest.requested_qty,
        )
        .first()
    )

    wo.actual_input_qty = passed
    wo.actual_output_qty = passed
    wo.passed_qty = passed
    wo.failed_qty = 0

    if wo.status not in ("cancelled", "rejected"):
        now = datetime.now(timezone.utc)
        if planned > 0 and processed >= planned and not has_open_replacements:
            if wo.status != "completed":
                wo.status = "completed"
            if not wo.end_time:
                wo.end_time = now
        elif processed > 0 and wo.status in ("new", "planning", "ready", "waiting", "pending", "collected", "paused"):
            wo.status = "in_progress"
            if not wo.start_time:
                wo.start_time = now
        elif processed <= 0 and wo.status in ("in_progress", "ready", "pending", "collected", "paused"):
            wo.status = "waiting"
            wo.start_time = None
            wo.end_time = None


def advance_workflow(
    db: Session,
    wo: WorkOrder,
    *,
    trigger_output_qty: int = 0,
    allow_next_stage_start: bool = True,
) -> None:
    _start_if_waiting(wo)
    _complete_if_done(db, wo)

    if allow_next_stage_start and trigger_output_qty > 0:
        by_op = _work_orders_by_op(
            db,
            wo.production_order_id,
            production_batch_id=wo.production_batch_id,
        )
        next_op = _next_existing_operation(wo.operation, by_op)
        if next_op:
            nxt = by_op.get(next_op)
            if nxt:
                if next_op == "printing":
                    _queue_printing_if_waiting(nxt)
                else:
                    _start_if_waiting(nxt)

    sync_production_order_status(db, wo.production_order_id)


def notify_department(
    db: Session,
    *,
    department_code: str,
    title: str,
    message: str | None = None,
    link: str | None = None,
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
        db.add(Notification(user_id=u.id, title=title, message=message, link=link))
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
    qry = db.query(StockBatch).filter(StockBatch.id == batch_id)
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
    batch = qry.first()
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
    warehouse_id: int | None = None,
    require_available: bool = False,
) -> float:
    if quantity <= 0:
        return 0.0
    left = float(quantity)
    consumed = 0.0

    batch_query = db.query(StockBatch).filter(StockBatch.item_id == item_id, StockBatch.quantity > 0)
    if warehouse_id is not None:
        batch_query = batch_query.filter(StockBatch.warehouse_id == warehouse_id)

    locked_batch_query = batch_query.order_by(StockBatch.received_date.asc(), StockBatch.id.asc())
    if db.bind and db.bind.dialect.name == "postgresql":
        locked_batch_query = locked_batch_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
    batches = locked_batch_query.all()

    if require_available:
        available = sum(float(row.quantity or 0) for row in batches)
        if available + 1e-9 < quantity:
            raise HTTPException(
                409,
                f"Insufficient stock for item #{item_id}: available {available}, requested {quantity}",
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
    qry = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package.id)
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.with_for_update(of=FinishedGoodsStock)
    rows = qry.all()
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
