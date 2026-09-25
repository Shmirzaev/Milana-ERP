from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, text
from sqlalchemy.orm import Session, lazyload

from app.models import (
    Department,
    FinishedGoodsStock,
    Invoice,
    Item,
    MaterialReservation,
    ModelBOM,
    Notification,
    Package,
    ProductionBatch,
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
from app.services.audit import log_action
from app.services.numbering import next_invoice_no

WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
_OP_INDEX = {op: idx for idx, op in enumerate(WORKFLOW_SEQUENCE)}
_STARTED_WORK_ORDER_STATUSES = {"in_progress", "pending", "collected", "ready"}
_MATERIAL_BATCH_CATEGORIES = {"fabric", "semi_finished"}
_STOCK_EPSILON = 1e-9
STOCK_ITEM_AVAILABILITY_LOCK_NAMESPACE = 1_297_047_633


def lock_stock_item_availability(db: Session, item_id: int) -> None:
    """Serialize writes competing with item-level reservation availability."""
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :item_id)"),
            {"namespace": STOCK_ITEM_AVAILABILITY_LOCK_NAMESPACE, "item_id": item_id},
        )


def archive_depleted_material_batch(
    db: Session,
    batch: StockBatch,
    *,
    user_id: int | None,
    item_cache: dict[int, Item] | None = None,
) -> bool:
    """Move a fully used fabric batch out of active stock without losing history."""
    if batch.archived_at is not None or float(batch.quantity or 0) > _STOCK_EPSILON:
        return False
    item = item_cache.get(int(batch.item_id)) if item_cache is not None else db.get(Item, int(batch.item_id))
    if not item or str(item.category or "").strip().lower() not in _MATERIAL_BATCH_CATEGORIES:
        return False
    batch.quantity = 0
    batch.archived_at = datetime.now(timezone.utc)
    batch.archived_by = user_id
    user = db.get(User, user_id) if user_id else None
    log_action(
        db,
        user,
        "archive_depleted",
        "StockBatch",
        int(batch.id),
        old_value={"quantity": 0, "archived_at": None},
        new_value={"quantity": 0, "archive_reason": "used"},
    )
    return True


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
    if wo.operation == "cutting":
        po = db.get(ProductionOrder, wo.production_order_id)
        if po and po.source_type == "usluga":
            if db.query(CuttingRecord.id).filter(
                CuttingRecord.work_order_id == wo.id,
                CuttingRecord.approval_status == "pending",
            ).first():
                return
            required_material_ids = {
                int(material_id)
                for (material_id,) in db.query(ModelBOM.id).filter(
                    ModelBOM.model_id == po.model_id,
                    ModelBOM.material_role.in_(("main", "secondary")),
                ).all()
            }
            approved_material_ids = {
                int(material_id)
                for (material_id,) in db.query(CuttingRecord.model_bom_id).filter(
                    CuttingRecord.work_order_id == wo.id,
                    CuttingRecord.approval_status == "approved",
                    CuttingRecord.model_bom_id.is_not(None),
                ).all()
            }
            if required_material_ids - approved_material_ids:
                return
            production_batch_ids = {
                int(batch_id)
                for (batch_id,) in db.query(ProductionBatch.id).filter(
                    ProductionBatch.production_order_id == wo.production_order_id,
                ).all()
            }
            if production_batch_ids:
                approved_main_batch_ids = {
                    int(batch_id)
                    for (batch_id,) in db.query(CuttingRecord.production_batch_id).filter(
                        CuttingRecord.work_order_id == wo.id,
                        CuttingRecord.material_role == "main",
                        CuttingRecord.approval_status == "approved",
                        CuttingRecord.production_batch_id.is_not(None),
                    ).all()
                }
                if production_batch_ids - approved_main_batch_ids:
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
    if po.source_type == "usluga":
        bundle_qry = bundle_qry.join(CuttingRecord, CuttingRecord.id == Bundle.cutting_record_id).filter(
            CuttingRecord.approval_status == "approved",
            CuttingRecord.material_role == "main",
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
            .filter(
                CuttingRecord.work_order_id == wo.id,
                *(
                    (
                        CuttingRecord.approval_status == "approved",
                        CuttingRecord.material_role == "main",
                    )
                    if po.source_type == "usluga"
                    else ()
                ),
            )
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


def sync_production_order_status(
    db: Session,
    production_order_id: int,
    *,
    production_order: ProductionOrder | None = None,
    work_orders: list[WorkOrder] | None = None,
) -> None:
    po = production_order or db.get(ProductionOrder, production_order_id)
    if not po:
        return
    all_wos = (
        work_orders
        if work_orders is not None
        else db.query(WorkOrder).filter(WorkOrder.production_order_id == production_order_id).all()
    )
    if not all_wos:
        po.status = "planning"
        return

    active = [w for w in all_wos if w.status not in ("completed", "rejected", "cancelled")]
    if not active:
        po.status = "ready_for_handover" if po.source_type == "usluga" and not po.handed_over_at else "finished_storage"
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
    recipient_cache: dict[str, tuple[int, ...]] | None = None,
) -> int:
    user_ids = recipient_cache.get(department_code) if recipient_cache is not None else None
    if user_ids is None:
        dept_id = db.query(Department.id).filter(Department.code == department_code).scalar()
        if not dept_id:
            user_ids = ()
        else:
            user_ids = tuple(
                int(user_id)
                for (user_id,) in db.query(User.id).filter(
                    User.department_id == dept_id,
                    User.is_active.is_(True),
                ).all()
            )
        if recipient_cache is not None:
            recipient_cache[department_code] = user_ids
    created = 0
    for user_id in user_ids:
        if exclude_user_id and user_id == exclude_user_id:
            continue
        db.add(Notification(user_id=user_id, title=title, message=message, link=link))
        created += 1
    return created


def _stock_consumption_unit(
    db: Session,
    *,
    item_id: int,
    unit: str | None,
    item_cache: dict[int, Item] | None,
) -> str:
    item = item_cache.get(item_id) if item_cache is not None else None
    if item is None:
        item = db.get(Item, item_id)
        if item is not None and item_cache is not None:
            item_cache[item_id] = item
    if item is None:
        raise HTTPException(404, f"Item {item_id} not found")
    expected_unit = str(item.unit or "").strip()
    requested_unit = str(unit or "").strip() or expected_unit
    if requested_unit != expected_unit:
        raise HTTPException(409, f"Consumption unit must match item unit ({expected_unit})")
    return requested_unit


def _require_batch_consumption_unit(batch: StockBatch, unit: str) -> None:
    batch_unit = str(batch.unit or "").strip()
    if unit != batch_unit:
        raise HTTPException(409, f"Consumption unit must match stock batch unit ({batch_unit})")


def batchless_stock_for_item(
    db: Session,
    item_id: int,
    warehouse_id: int | None = None,
    *,
    unscoped_only: bool = False,
) -> Decimal:
    """Return stock represented only by unbatched movements, at ledger precision."""
    incoming_types = ("produce", "return", "adjustment")
    outgoing_types = ("issue", "consume", "waste", "shipment")
    incoming = StockMovement.movement_type.in_(incoming_types)
    outgoing = StockMovement.movement_type.in_(outgoing_types)
    if warehouse_id is not None:
        incoming = or_(
            and_(incoming, StockMovement.to_warehouse_id == warehouse_id),
            and_(StockMovement.movement_type == "transfer", StockMovement.to_warehouse_id == warehouse_id),
        )
        outgoing = or_(
            and_(outgoing, StockMovement.from_warehouse_id == warehouse_id),
            and_(StockMovement.movement_type == "transfer", StockMovement.from_warehouse_id == warehouse_id),
        )
    movement_query = db.query(
        func.coalesce(func.sum(case((incoming, StockMovement.quantity), else_=0)), 0),
        func.coalesce(func.sum(case((outgoing, StockMovement.quantity), else_=0)), 0),
    ).filter(
        StockMovement.item_id == item_id,
        StockMovement.batch_id.is_(None),
    )
    if unscoped_only:
        movement_query = movement_query.filter(
            StockMovement.to_warehouse_id.is_(None),
            StockMovement.from_warehouse_id.is_(None),
        )
    received, spent = movement_query.one()
    return Decimal(str(received or 0)) - Decimal(str(spent or 0))


def consume_stock_batch(
    db: Session,
    *,
    batch_id: int,
    quantity: float,
    unit: str,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
    batch_cache: dict[int, StockBatch] | None = None,
    item_cache: dict[int, Item] | None = None,
) -> None:
    if quantity <= 0:
        return
    if batch_cache is None:
        qry = db.query(StockBatch).filter(StockBatch.id == batch_id)
        if db.bind and db.bind.dialect.name == "postgresql":
            qry = qry.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        batch = qry.first()
    else:
        batch = batch_cache.get(batch_id)
    if not batch:
        raise HTTPException(404, f"Stock batch {batch_id} not found")
    effective_unit = _stock_consumption_unit(
        db, item_id=int(batch.item_id), unit=unit or batch.unit, item_cache=item_cache,
    )
    _require_batch_consumption_unit(batch, effective_unit)
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
            unit=effective_unit,
            unit_cost_at_movement=batch.cost_per_unit,
            cost_currency_at_movement=batch.cost_currency,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=user_id,
        )
    )
    archive_depleted_material_batch(db, batch, user_id=user_id, item_cache=item_cache)


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
    batch_cache: dict[int, list[StockBatch]] | None = None,
    reserved_by_batch: dict[int, Decimal] | None = None,
    item_cache: dict[int, Item] | None = None,
) -> float:
    if quantity <= 0:
        return 0.0
    left = float(quantity)
    consumed = 0.0

    if batch_cache is None:
        batch_query = db.query(StockBatch).filter(StockBatch.item_id == item_id, StockBatch.quantity > 0)
        if warehouse_id is not None:
            batch_query = batch_query.filter(StockBatch.warehouse_id == warehouse_id)

        # Reservation creation locks batches by ID. Acquire those row locks in
        # the same order, then choose FIFO consumption from the locked rows.
        locked_batch_query = batch_query.order_by(StockBatch.id.asc())
        if db.bind and db.bind.dialect.name == "postgresql":
            locked_batch_query = locked_batch_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        batches = locked_batch_query.all()
        batches.sort(key=lambda batch: (batch.received_date, batch.id))
    else:
        batches = [
            batch
            for batch in batch_cache.get(item_id, [])
            if warehouse_id is None or batch.warehouse_id == warehouse_id
        ]

    effective_unit = _stock_consumption_unit(
        db, item_id=int(item_id), unit=unit, item_cache=item_cache,
    )

    if require_available:
        # Batch locks were acquired above; match reservation creation's
        # batch-before-item lock order before reading the shared ledger.
        lock_stock_item_availability(db, int(item_id))
        if reserved_by_batch is None and batches:
            reserved_by_batch = {
                int(batch_id): max(Decimal(0), Decimal(str(quantity or 0)))
                for batch_id, quantity in db.query(
                    MaterialReservation.stock_batch_id,
                    func.sum(
                        MaterialReservation.reserved_quantity
                        - MaterialReservation.consumed_quantity
                        - MaterialReservation.released_quantity
                    ),
                ).filter(
                    MaterialReservation.stock_batch_id.in_(int(batch.id) for batch in batches),
                    MaterialReservation.status.in_(("reserved", "partially_consumed")),
                ).group_by(MaterialReservation.stock_batch_id).all()
            }
    batchless_available = (
        batchless_stock_for_item(db, item_id, warehouse_id, unscoped_only=warehouse_id is None)
        if require_available else Decimal(0)
    )
    if require_available:
        available = sum(
            max(Decimal(0), Decimal(str(row.quantity or 0)) - (reserved_by_batch or {}).get(int(row.id), Decimal(0)))
            for row in batches
        ) + batchless_available
        if available + Decimal("0.000000001") < Decimal(str(quantity)):
            raise HTTPException(
                409,
                f"Insufficient stock for item #{item_id}: available {available}, requested {quantity}",
            )
    planned_batches: list[tuple[StockBatch, float]] = []
    planned_left = left
    for batch in batches:
        if planned_left <= 0:
            break
        unreserved = max(
            Decimal(0), Decimal(str(batch.quantity or 0)) - (reserved_by_batch or {}).get(int(batch.id), Decimal(0)),
        )
        take = min(planned_left, float(unreserved))
        if take <= 0:
            continue
        _require_batch_consumption_unit(batch, effective_unit)
        planned_batches.append((batch, take))
        planned_left -= take

    for b, take in planned_batches:
        if left <= 0:
            break
        b.quantity = float(b.quantity or 0) - take
        db.add(
            StockMovement(
                movement_type="consume",
                item_id=item_id,
                batch_id=b.id,
                from_warehouse_id=b.warehouse_id,
                to_warehouse_id=None,
                quantity=take,
                unit=effective_unit,
                unit_cost_at_movement=b.cost_per_unit,
                cost_currency_at_movement=b.cost_currency,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=user_id,
            )
        )
        archive_depleted_material_batch(db, b, user_id=user_id, item_cache=item_cache)
        consumed += take
        left -= take

    if left > _STOCK_EPSILON:
        # A partial batch shortage must record the remainder just as an item
        # with no batches does, so the business action has one complete ledger.
        db.add(
            StockMovement(
                movement_type="consume",
                item_id=item_id,
                batch_id=None,
                from_warehouse_id=warehouse_id,
                quantity=left,
                unit=effective_unit,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=user_id,
            )
        )
        consumed += left
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
    items = {
        item.id: item
        for item in db.query(Item).filter(Item.id.in_(sorted({row.item_id for row in bom_rows}))).all()
    }
    packaging_rows = [
        (row, item)
        for row in bom_rows
        if (item := items.get(row.item_id)) is not None and item.category == "packaging"
    ]
    packaging_item_ids = sorted({item.id for _row, item in packaging_rows})
    batch_cache: dict[int, list[StockBatch]] = {item_id: [] for item_id in packaging_item_ids}
    batches_by_id: dict[int, StockBatch] = {}
    reserved_by_batch: dict[int, Decimal] = {}
    own_reservations_by_item: dict[int, list[MaterialReservation]] = {}
    own_item_only_by_item: dict[int, list[MaterialReservation]] = {}
    if packaging_item_ids:
        db.flush()
        batch_query = (
            db.query(StockBatch)
            .filter(
                StockBatch.item_id.in_(packaging_item_ids),
                StockBatch.quantity > 0,
            )
            .order_by(StockBatch.id.asc())
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            batch_query = batch_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        for batch in batch_query.all():
            batch_cache[batch.item_id].append(batch)
            batches_by_id[int(batch.id)] = batch
        for batches in batch_cache.values():
            batches.sort(key=lambda batch: (batch.received_date, batch.id))
        if db.bind and db.bind.dialect.name == "postgresql":
            db.execute(
                text(
                    "SELECT pg_advisory_xact_lock(:namespace, lock_id) "
                    "FROM unnest(CAST(:item_ids AS INTEGER[])) AS ordered_locks(lock_id) "
                    "ORDER BY lock_id"
                ),
                {"namespace": STOCK_ITEM_AVAILABILITY_LOCK_NAMESPACE, "item_ids": packaging_item_ids},
            )
        if batches_by_id:
            # Reservation consumers lock batches before reservation rows. Read
            # all active batch claims in one locked set so a BOM debit cannot
            # take stock promised to another production order.
            db.flush()
            reservations = db.query(MaterialReservation).options(
                lazyload(MaterialReservation.item),
                lazyload(MaterialReservation.stock_batch),
                lazyload(MaterialReservation.warehouse),
            ).filter(
                MaterialReservation.stock_batch_id.in_(sorted(batches_by_id)),
                MaterialReservation.status.in_(("reserved", "partially_consumed")),
            ).order_by(
                MaterialReservation.stock_batch_id,
                MaterialReservation.created_at,
                MaterialReservation.id,
            ).populate_existing()
            if db.bind and db.bind.dialect.name == "postgresql":
                reservations = reservations.with_for_update(of=MaterialReservation)
            for reservation in reservations.all():
                remaining = max(
                    Decimal(0),
                    Decimal(str(reservation.reserved_quantity or 0))
                    - Decimal(str(reservation.consumed_quantity or 0))
                    - Decimal(str(reservation.released_quantity or 0)),
                )
                if remaining <= 0:
                    continue
                batch_id = int(reservation.stock_batch_id)
                reserved_by_batch[batch_id] = reserved_by_batch.get(batch_id, Decimal(0)) + remaining
                if int(reservation.production_order_id) == production_order_id:
                    own_reservations_by_item.setdefault(int(reservation.item_id), []).append(reservation)
            for reservations_for_item in own_reservations_by_item.values():
                reservations_for_item.sort(key=lambda reservation: (
                    batches_by_id[int(reservation.stock_batch_id)].received_date,
                    int(reservation.stock_batch_id),
                    reservation.created_at,
                    int(reservation.id),
                ))
        item_only_rows = db.query(MaterialReservation).options(
            lazyload(MaterialReservation.item),
            lazyload(MaterialReservation.stock_batch),
            lazyload(MaterialReservation.warehouse),
        ).filter(
            MaterialReservation.production_order_id == production_order_id,
            MaterialReservation.item_id.in_(packaging_item_ids),
            MaterialReservation.stock_batch_id.is_(None),
            MaterialReservation.status.in_(("reserved", "partially_consumed")),
        ).order_by(
            MaterialReservation.item_id,
            MaterialReservation.created_at,
            MaterialReservation.id,
        ).populate_existing()
        if db.bind and db.bind.dialect.name == "postgresql":
            item_only_rows = item_only_rows.with_for_update(of=MaterialReservation)
        for reservation in item_only_rows.all():
            own_item_only_by_item.setdefault(int(reservation.item_id), []).append(reservation)

    demand_by_item: dict[int, Decimal] = {}
    for row, item in packaging_rows:
        demand_by_item[int(item.id)] = demand_by_item.get(int(item.id), Decimal(0)) + Decimal(str(
            float(row.quantity_per_piece) * packed_qty * (1.0 + float(row.waste_percent or 0) / 100.0)
        ))
    own_item_only_planned_by_scope: dict[tuple[int, int], Decimal] = {}
    own_item_only_claim_by_item: dict[int, Decimal] = {}
    for item_id, own_rows in own_item_only_by_item.items():
        own_bound = sum((
            max(
                Decimal(0), Decimal(str(reservation.reserved_quantity or 0))
                - Decimal(str(reservation.consumed_quantity or 0))
                - Decimal(str(reservation.released_quantity or 0)),
            )
            for reservation in own_reservations_by_item.get(item_id, [])
        ), Decimal(0))
        left = max(Decimal(0), demand_by_item.get(item_id, Decimal(0)) - own_bound)
        for reservation in own_rows:
            open_quantity = max(
                Decimal(0), Decimal(str(reservation.reserved_quantity or 0))
                - Decimal(str(reservation.consumed_quantity or 0))
                - Decimal(str(reservation.released_quantity or 0)),
            )
            planned = min(left, open_quantity)
            own_item_only_claim_by_item[item_id] = own_item_only_claim_by_item.get(item_id, Decimal(0)) + planned
            if planned > 0 and reservation.warehouse_id is not None:
                key = (item_id, int(reservation.warehouse_id))
                own_item_only_planned_by_scope[key] = own_item_only_planned_by_scope.get(key, Decimal(0)) + planned
            left -= planned
    # Packaging may record a non-strict shortage only when no active claim is
    # reduced. Preflight every item before the first movement so a later BOM
    # line cannot leave an earlier line staged on a reservation conflict.
    active_totals = {
        int(item_id): Decimal(str(quantity or 0))
        for item_id, quantity in db.query(
            MaterialReservation.item_id,
            func.sum(
                MaterialReservation.reserved_quantity
                - MaterialReservation.consumed_quantity
                - MaterialReservation.released_quantity
            ),
        ).filter(
            MaterialReservation.item_id.in_(packaging_item_ids),
            MaterialReservation.status.in_(("reserved", "partially_consumed")),
        ).group_by(MaterialReservation.item_id).all()
    } if packaging_item_ids else {}
    reserved_items = sorted(item_id for item_id, total in active_totals.items() if total > 0)
    batchless_by_item: dict[int, Decimal] = {}
    if reserved_items:
        incoming = StockMovement.movement_type.in_(("produce", "return", "adjustment"))
        outgoing = StockMovement.movement_type.in_(("issue", "consume", "waste", "shipment"))
        batchless_by_item = {
            int(item_id): Decimal(str(received or 0)) - Decimal(str(spent or 0))
            for item_id, received, spent in db.query(
                StockMovement.item_id,
                func.coalesce(func.sum(case((incoming, StockMovement.quantity), else_=0)), 0),
                func.coalesce(func.sum(case((outgoing, StockMovement.quantity), else_=0)), 0),
            ).filter(
                StockMovement.item_id.in_(reserved_items),
                StockMovement.batch_id.is_(None),
            ).group_by(StockMovement.item_id).all()
        }
    own_claim_by_item: dict[int, Decimal] = {}
    for item_id in reserved_items:
        batches = batch_cache[item_id]
        cached_reserved = sum(
            (reserved_by_batch.get(int(batch.id), Decimal(0)) for batch in batches), Decimal(0),
        )
        if any(
            reserved_by_batch.get(int(batch.id), Decimal(0)) > Decimal(str(batch.quantity or 0))
            for batch in batches
        ):
            raise HTTPException(409, f"Packaging stock for item #{item_id} cannot preserve active reservations")
        own_claim = sum(
            (
                max(
                    Decimal(0),
                    Decimal(str(reservation.reserved_quantity or 0))
                    - Decimal(str(reservation.consumed_quantity or 0))
                    - Decimal(str(reservation.released_quantity or 0)),
                )
                for reservation in own_reservations_by_item.get(item_id, [])
            ), Decimal(0),
        )
        own_claim += own_item_only_claim_by_item.get(item_id, Decimal(0))
        own_claim_by_item[item_id] = own_claim
        free_batches = sum((
            max(Decimal(0), Decimal(str(batch.quantity or 0)) - reserved_by_batch.get(int(batch.id), Decimal(0)))
            for batch in batches
        ), Decimal(0))
        unbacked_claims = max(Decimal(0), active_totals[item_id] - cached_reserved)
        batchless = batchless_by_item.get(item_id, Decimal(0))
        # Batch-bound claims remain backed by their locked batches even when
        # an older batchless shortage already exists. Item-only claims rely on
        # the global ledger and must account for that existing debt.
        usable_batchless = batchless if unbacked_claims > 0 else max(Decimal(0), batchless)
        safe_capacity = own_claim + free_batches + usable_batchless - unbacked_claims
        if demand_by_item.get(item_id, Decimal(0)) > safe_capacity + Decimal("0.000000001"):
            raise HTTPException(409, f"Packaging stock for item #{item_id} cannot preserve active reservations")

    protected_by_batch = dict(reserved_by_batch)
    if reserved_items:
        scoped_item_only_claims = db.query(
            MaterialReservation.item_id,
            MaterialReservation.warehouse_id,
            func.sum(
                MaterialReservation.reserved_quantity
                - MaterialReservation.consumed_quantity
                - MaterialReservation.released_quantity
            ),
        ).filter(
            MaterialReservation.item_id.in_(reserved_items),
            MaterialReservation.stock_batch_id.is_(None),
            MaterialReservation.warehouse_id.is_not(None),
            MaterialReservation.status.in_(("reserved", "partially_consumed")),
        ).group_by(MaterialReservation.item_id, MaterialReservation.warehouse_id).all()
        scoped_item_ids = sorted({int(item_id) for item_id, _warehouse_id, _claim in scoped_item_only_claims})
        scoped_warehouse_ids = sorted({int(warehouse_id) for _item_id, warehouse_id, _claim in scoped_item_only_claims})
        batchless_in: dict[tuple[int, int], Decimal] = {}
        batchless_out: dict[tuple[int, int], Decimal] = {}
        if scoped_item_ids:
            batchless_in = {
                (int(item_id), int(warehouse_id)): Decimal(str(quantity or 0))
                for item_id, warehouse_id, quantity in db.query(
                    StockMovement.item_id,
                    StockMovement.to_warehouse_id,
                    func.sum(StockMovement.quantity),
                ).filter(
                    StockMovement.item_id.in_(scoped_item_ids),
                    StockMovement.batch_id.is_(None),
                    StockMovement.to_warehouse_id.in_(scoped_warehouse_ids),
                    StockMovement.movement_type.in_(("produce", "return", "adjustment", "transfer")),
                ).group_by(StockMovement.item_id, StockMovement.to_warehouse_id).all()
            }
            batchless_out = {
                (int(item_id), int(warehouse_id)): Decimal(str(quantity or 0))
                for item_id, warehouse_id, quantity in db.query(
                    StockMovement.item_id,
                    StockMovement.from_warehouse_id,
                    func.sum(StockMovement.quantity),
                ).filter(
                    StockMovement.item_id.in_(scoped_item_ids),
                    StockMovement.batch_id.is_(None),
                    StockMovement.from_warehouse_id.in_(scoped_warehouse_ids),
                    StockMovement.movement_type.in_(("issue", "consume", "waste", "shipment", "transfer")),
                ).group_by(StockMovement.item_id, StockMovement.from_warehouse_id).all()
            }
        for item_id, warehouse_id, claim in scoped_item_only_claims:
            scoped_key = (int(item_id), int(warehouse_id))
            remaining = max(
                Decimal(0),
                Decimal(str(claim or 0)) - own_item_only_planned_by_scope.get(scoped_key, Decimal(0)),
            )
            # Keep newest batches as backing so free older batches retain FIFO
            # consumption order. The rest may already be backed by the scoped
            # batchless ledger, which this operation leaves in that warehouse.
            for batch in reversed(batch_cache[int(item_id)]):
                if int(batch.warehouse_id) != int(warehouse_id) or remaining <= 0:
                    continue
                batch_id = int(batch.id)
                free = max(Decimal(0), Decimal(str(batch.quantity or 0)) - protected_by_batch.get(batch_id, Decimal(0)))
                protected = min(free, remaining)
                protected_by_batch[batch_id] = protected_by_batch.get(batch_id, Decimal(0)) + protected
                remaining -= protected
            scoped_batchless = batchless_in.get(scoped_key, Decimal(0)) - batchless_out.get(scoped_key, Decimal(0))
            if remaining > scoped_batchless + Decimal("0.000000001"):
                raise HTTPException(
                    409, f"Packaging stock for item #{item_id} cannot preserve warehouse reservations",
                )
        for item_id in scoped_item_ids:
            physical_capacity = own_claim_by_item[item_id] + sum((
                max(Decimal(0), Decimal(str(batch.quantity or 0)) - protected_by_batch.get(int(batch.id), Decimal(0)))
                for batch in batch_cache[item_id]
            ), Decimal(0))
            if demand_by_item.get(item_id, Decimal(0)) > physical_capacity + Decimal("0.000000001"):
                raise HTTPException(
                    409, f"Packaging stock for item #{item_id} cannot preserve warehouse reservations",
                )

    for row, item in packaging_rows:
        qty = float(row.quantity_per_piece) * packed_qty * (1.0 + float(row.waste_percent or 0) / 100.0)
        if qty <= 0:
            continue
        unit = _stock_consumption_unit(db, item_id=int(item.id), unit=row.unit or item.unit, item_cache=items)
        left = qty
        if own_reservations_by_item.get(int(item.id)):
            from app.services.inventory import _consume_loaded_material_reservation, _open_reservation_quantity

            for reservation in own_reservations_by_item[int(item.id)]:
                if left <= _STOCK_EPSILON:
                    break
                take = min(left, _open_reservation_quantity(reservation))
                if take <= _STOCK_EPSILON:
                    continue
                batch_id = int(reservation.stock_batch_id)
                _consume_loaded_material_reservation(
                    db, reservation, quantity=take, user_id=user_id,
                    reference_type=reference_type, reference_id=reference_id,
                    stock_batch_cache={batch_id: batches_by_id[batch_id]}, item_cache=items,
                )
                reserved_by_batch[batch_id] = max(
                    Decimal(0), reserved_by_batch[batch_id] - Decimal(str(take)),
                )
                protected_by_batch[batch_id] = max(
                    Decimal(0), protected_by_batch[batch_id] - Decimal(str(take)),
                )
                left -= take
        if left > _STOCK_EPSILON and own_item_only_by_item.get(int(item.id)):
            from app.services.inventory import _open_reservation_quantity, _set_reservation_status

            for reservation in own_item_only_by_item[int(item.id)]:
                if left <= _STOCK_EPSILON:
                    break
                take = min(left, _open_reservation_quantity(reservation))
                if take <= _STOCK_EPSILON:
                    continue
                if str(reservation.unit or "").strip() != unit:
                    raise HTTPException(409, "Packaging reservation unit must match item unit")
                consume_item_from_batches(
                    db,
                    item_id=item.id,
                    quantity=take,
                    unit=unit,
                    reference_type=reference_type,
                    reference_id=reference_id,
                    user_id=user_id,
                    warehouse_id=int(reservation.warehouse_id) if reservation.warehouse_id is not None else None,
                    require_available=True,
                    batch_cache=batch_cache,
                    reserved_by_batch=protected_by_batch,
                    item_cache=items,
                )
                reservation.consumed_quantity = float(reservation.consumed_quantity or 0) + take
                _set_reservation_status(reservation)
                db.flush()
                left -= take
        if left > _STOCK_EPSILON:
            consume_item_from_batches(
                db,
                item_id=item.id,
                quantity=left,
                unit=unit,
                reference_type=reference_type,
                reference_id=reference_id,
                user_id=user_id,
                batch_cache=batch_cache,
                reserved_by_batch=protected_by_batch,
                item_cache=items,
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
        currency=so.currency,
        status="unpaid",
        issued_at=now,
        due_date=due,
    )
    db.add(inv)
    return inv
