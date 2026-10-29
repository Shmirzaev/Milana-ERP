from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session, lazyload

from app.schemas.core_persistence import add_notification_row
from app.schemas.inventory import stock_movement_persistence

from app.schemas import (
    Department,
    FinishedGoodsStock,
    Invoice,
    Item,
    ModelBOM,
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
)
from app.models.audit_service import log_action
from app.models.numbering_service import next_invoice_no
from app.libs.enums.finance import InvoiceStatus
from app.models.passport_nastil_service import has_pending_passport_batches

WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
_OP_INDEX = {op: idx for idx, op in enumerate(WORKFLOW_SEQUENCE)}
_STARTED_WORK_ORDER_STATUSES = {"in_progress", "pending", "collected", "ready"}
_MATERIAL_BATCH_CATEGORIES = {"fabric", "semi_finished"}
_STOCK_EPSILON = 1e-9


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
    stock_movement_persistence.archive_batch(
        db, batch, archived_at=datetime.now(timezone.utc), user_id=user_id,
    )
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
    # Read legacy loss credit and the ownership discriminator together. Ordinary
    # orders retain the existing one-round-trip completion budget.
    # A shortage already supplied by a later Nastil cannot reduce the target.
    remaining = case(
        (WorkOrder.planned_output_qty > WorkOrder.passed_qty,
         WorkOrder.planned_output_qty - WorkOrder.passed_qty),
        else_=0,
    )
    effective_failed = case(
        (WorkOrder.failed_qty > remaining, remaining),
        else_=WorkOrder.failed_qty,
    )
    qry = db.query(func.coalesce(func.sum(effective_failed), 0)).filter(
        WorkOrder.production_order_id == wo.production_order_id,
        WorkOrder.operation.in_(prior_operations),
        WorkOrder.production_batch_id.is_(None) if wo.production_batch_id is None
        else WorkOrder.production_batch_id == wo.production_batch_id,
    )
    scoped_operation = wo.operation in {"sewing", "packaging"}
    dedicated_exists = wo.production_batch_id is not None
    if scoped_operation and not dedicated_exists:
        dedicated_query = db.query(WorkOrder.id).filter(
            WorkOrder.production_order_id == wo.production_order_id,
            WorkOrder.operation == wo.operation, WorkOrder.production_batch_id.is_not(None),
            WorkOrder.status != "cancelled")
        legacy_failed, dedicated_exists = db.query(qry.scalar_subquery(), dedicated_query.exists()).one()
        if not dedicated_exists:
            return int(legacy_failed or 0)
    if dedicated_exists and scoped_operation:
        from app.schemas import PrintingRecord, SewingRecord
        from app.models.production.batch_scope_service import filter_work_order_batches
        total = 0
        for operation, model, loss in (("cutting", CuttingRecord, CuttingRecord.defective_pieces),
                ("printing", PrintingRecord, PrintingRecord.rejected_qty),
                ("sewing", SewingRecord, SewingRecord.failed_qty + SewingRecord.rejected_qty)):
            if operation not in prior_operations:
                continue
            # Dedicated stages start from usable bundles, which already exclude
            # cutting defects. Only subsequent Printing/Sewing losses reduce them.
            if operation == "cutting" and wo.production_batch_id is not None:
                continue
            query = db.query(func.coalesce(func.sum(loss), 0)).join(WorkOrder, WorkOrder.id == model.work_order_id).filter(
                WorkOrder.production_order_id == wo.production_order_id, WorkOrder.status.notin_({"cancelled", "rejected"}))
            if operation == "cutting":
                query = query.filter(CuttingRecord.approval_status == "approved",
                    func.coalesce(CuttingRecord.material_role, "main") == "main")
            total += int(filter_work_order_batches(query, model.production_batch_id, wo).scalar() or 0)
        return total
    return int(qry.scalar() or 0)


def processed_work_order_qty(db: Session, wo: WorkOrder) -> int:
    planned = max(0, int(wo.planned_output_qty or 0))
    own_failed = int(wo.failed_qty or 0)
    processed = int(wo.passed_qty or 0) + own_failed + _upstream_failed_qty(db, wo)
    return min(planned, processed) if planned > 0 else max(0, processed)


def _complete_if_done(db: Session, wo: WorkOrder) -> None:
    pending_sewing = False
    if wo.operation == "sewing":
        from app.models.sewing_progress_service import unfinished_sewing_batches
        pending_sewing = bool(unfinished_sewing_batches(db, wo))
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
        elif has_pending_passport_batches(db, wo):
            return
    planned = int(wo.planned_output_qty or 0)
    processed = processed_work_order_qty(db, wo)
    if planned > 0 and processed >= planned and not pending_sewing and wo.status != "completed":
        wo.status = "completed"
        wo.end_time = datetime.now(timezone.utc)
    elif wo.operation in ("sewing", "packaging") and (processed < planned or pending_sewing) and wo.status == "completed":
        wo.status = "in_progress"
        wo.end_time = None


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

    record_qry = db.query(func.coalesce(func.sum(CuttingRecord.total_bundled_quantity), 0)).filter(
        CuttingRecord.work_order_id == wo.id,
        *((CuttingRecord.approval_status == "approved", CuttingRecord.material_role == "main")
          if po.source_type == "usluga" else ()),
    )
    # Read both output sources together, leaving no extra round trip for the
    # pending-Nastil completion guard that follows this plan propagation.
    if po.source_type == "usluga":
        recorded_qty, bundled_qty = record_qry.scalar(), bundle_qry.scalar()
    else:
        recorded_qty, bundled_qty = db.query(record_qry.scalar_subquery(), bundle_qry.scalar_subquery()).one()
    output_qty = max(0, int(wo.actual_output_qty or 0), int(wo.passed_qty or 0),
                     int(recorded_qty or 0), int(bundled_qty or 0))
    if output_qty <= 0:
        return

    downstream_ops = WORKFLOW_SEQUENCE[WORKFLOW_SEQUENCE.index("cutting") + 1 :]
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == wo.production_order_id,
        WorkOrder.operation.in_(downstream_ops),
    )
    if wo.production_batch_id is not None:
        qry = qry.filter(WorkOrder.production_batch_id == wo.production_batch_id)

    downstream = qry.all()
    dedicated = [row for row in downstream if row.production_batch_id is not None]
    batch_outputs = {}
    if dedicated:
        for bid, qty in db.query(Bundle.production_batch_id, func.sum(Bundle.quantity)).filter(
            Bundle.production_order_id == wo.production_order_id, Bundle.status != "cancelled").group_by(Bundle.production_batch_id):
            batch_outputs[bid] = max(0, int(qty or 0))
        for bid, qty in db.query(CuttingRecord.production_batch_id, func.sum(CuttingRecord.passed_pieces)).filter(
            CuttingRecord.work_order_id == wo.id, CuttingRecord.approval_status == "approved").group_by(CuttingRecord.production_batch_id):
            batch_outputs[bid] = max(batch_outputs.get(bid, 0), int(qty or 0))
    for row in downstream:
        target = output_qty
        if dedicated and row.operation in {"sewing", "packaging"}:
            owned_elsewhere = {other.production_batch_id for other in dedicated if other.operation == row.operation}
            target = (batch_outputs.get(row.production_batch_id, 0) if row.production_batch_id is not None else
                      max(0, output_qty - sum(batch_outputs.get(bid, 0) for bid in owned_elsewhere)))
        if int(row.planned_input_qty or 0) < target:
            row.planned_input_qty = target
        if int(row.planned_output_qty or 0) < target:
            row.planned_output_qty = target


def sync_production_order_status(
    db: Session, production_order_id: int, *,
    production_order: ProductionOrder | None = None,
    work_orders: list[WorkOrder] | None = None,
) -> None:
    po = production_order if production_order is not None else db.get(ProductionOrder, production_order_id)
    if not po:
        return
    all_wos = work_orders if work_orders is not None else db.query(WorkOrder).filter(WorkOrder.production_order_id == production_order_id).all()
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

    wo.actual_input_qty = passed
    wo.actual_output_qty = passed
    wo.passed_qty = passed
    wo.failed_qty = 0

    if wo.status not in ("cancelled", "rejected"):
        now = datetime.now(timezone.utc)
        if planned > 0 and processed >= planned:
            if wo.status != "completed":
                # A batched receipt can move directly from waiting to complete.
                # Keep its start event just as sequential partial receipts do.
                if passed > 0 and not wo.start_time:
                    wo.start_time = now
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
    if trigger_output_qty > 0:
        by_op = _work_orders_by_op(
            db,
            wo.production_order_id,
            production_batch_id=wo.production_batch_id,
        )
        sewing = by_op.get("sewing")
        if wo.operation in ("cutting", "printing") and sewing and sewing.status == "completed":
            from app.models.sewing_progress_service import reconcile_sewing_order
            reconcile_sewing_order(db, wo.production_order_id, reason=f"{wo.operation} output reconciled")
        next_op = _next_existing_operation(wo.operation, by_op) if allow_next_stage_start else None
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
        add_notification_row(db, user_id=user_id, title=title, message=message, link=link)
        created += 1
    return created


def _stock_consumption_unit(
    db: Session,
    *,
    item_id: int,
    unit: str | None,
    item_cache: dict[int, Item] | None = None,
) -> str:
    item = item_cache.get(item_id) if item_cache is not None else db.get(Item, item_id)
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
    effective_unit = _stock_consumption_unit(db, item_id=int(batch.item_id), unit=unit or batch.unit, item_cache=item_cache)
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

        locked_batch_query = batch_query.order_by(StockBatch.received_date.asc(), StockBatch.id.asc())
        if db.bind and db.bind.dialect.name == "postgresql":
            locked_batch_query = locked_batch_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        batches = locked_batch_query.all()
    else:
        batches = [batch for batch in batch_cache.get(item_id, [])
                   if warehouse_id is None or batch.warehouse_id == warehouse_id]
    effective_unit = _stock_consumption_unit(db, item_id=int(item_id), unit=unit, item_cache=item_cache)

    if require_available:
        available = sum(float(row.quantity or 0) for row in batches)
        if available + 1e-9 < quantity:
            raise HTTPException(
                409,
                f"Insufficient stock for item #{item_id}: available {available}, requested {quantity}",
            )
    planned_batches: list[tuple[StockBatch, float]] = []
    planned_left = left
    for batch in batches:
        if planned_left <= 0:
            break
        take = min(planned_left, float(batch.quantity or 0))
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
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=user_id,
            )
        )
        archive_depleted_material_batch(db, b, user_id=user_id, item_cache=item_cache)
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
                unit=effective_unit,
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
    if packaging_item_ids:
        batch_query = (
            db.query(StockBatch)
            .filter(
                StockBatch.item_id.in_(packaging_item_ids),
                StockBatch.quantity > 0,
            )
            .order_by(
                StockBatch.item_id.asc(),
                StockBatch.received_date.asc(),
                StockBatch.id.asc(),
            )
        )
        if db.bind and db.bind.dialect.name == "postgresql":
            batch_query = batch_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        for batch in batch_query.all():
            batch_cache[batch.item_id].append(batch)

    for row, item in packaging_rows:
        qty = float(row.quantity_per_piece) * packed_qty * (1.0 + float(row.waste_percent or 0) / 100.0)
        consume_item_from_batches(
            db,
            item_id=item.id,
            quantity=qty,
            unit=row.unit or item.unit,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            batch_cache=batch_cache,
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


def decrement_finished_goods_for_package(
    db: Session, package: Package, *, rows: list[FinishedGoodsStock] | None = None,
) -> None:
    if rows is None:
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
    existing = db.query(Invoice).filter(
        Invoice.sales_order_id == sales_order_id,
        Invoice.status.notin_([InvoiceStatus.VOID.value, InvoiceStatus.CANCELLED.value]),
    ).first()
    if existing:
        return existing
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=14)
    inv = Invoice(
        sales_order_id=sales_order_id,
        invoice_no=next_invoice_no(db),
        amount=float(so.total_amount or 0),
        status=InvoiceStatus.UNPAID,
        issued_at=now,
        due_date=due,
    )
    db.add(inv)
    return inv
