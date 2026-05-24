from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.models import (
    ProductionOrder, WorkOrder, CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord,
    SalesOrder, QualityCheck, User, SewingFlow, SewingAssignment, Package, ProductionBatch, WasteRecord,
)
from app.schemas.production import (
    ProductionOrderIn, ProductionOrderOut, ProductionOrderDetail,
    WorkOrderOut, WorkOrderUpdate,
    CuttingRecordIn, PrintingRecordIn, SewingRecordIn, PackagingRecordIn,
    QualityCheckIn, QualityCheckOut,
)
from app.core.dt import as_utc
from app.services.audit import log_action
from app.services.production import create_production_order, create_production_batches, create_work_orders
from app.services.bundles import create_bundle
from app.services.packages import create_package
from app.services.workflow import (
    advance_workflow,
    consume_packaging_materials_from_bom,
    consume_stock_batch,
    create_waste_record,
    notify_department,
    sync_production_order_status,
)

router = APIRouter(tags=["production"])

_ACTIVE_WO_STATUSES = ("waiting", "pending", "collected", "ready", "in_progress", "paused", "new", "planning")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")


class PrintingCollectIn(BaseModel):
    deadline: datetime
    notes: str | None = None


class SplitBatchLineIn(BaseModel):
    name: str | None = None
    planned_quantity: int
    start_date: datetime | None = None
    deadline: datetime | None = None
    notes: str | None = None


class SplitWorkOrderBatchesIn(BaseModel):
    batches: list[SplitBatchLineIn]


def _ordered_batches_for_work_order(db: DbSession, wo: WorkOrder) -> tuple[ProductionOrder, list[ProductionBatch]]:
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    batches = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.production_order_id == po.id)
        .order_by(ProductionBatch.batch_index.asc(), ProductionBatch.id.asc())
        .all()
    )
    return po, batches


def _resolve_record_batch_id(
    db: DbSession,
    wo: WorkOrder,
    payload_batch_id: int | None,
    *,
    operation_name: str,
) -> int | None:
    normalized = int(payload_batch_id) if payload_batch_id else None

    # Legacy mode: one WO per batch (or explicitly batch-tied WO)
    if wo.production_batch_id is not None:
        expected = int(wo.production_batch_id)
        if normalized is not None and normalized != expected:
            raise HTTPException(400, f"This work order is bound to batch #{expected}")
        return expected

    po, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return None

    if normalized is None:
        raise HTTPException(400, f"Select a production batch for this {operation_name} record")

    exists = db.query(ProductionBatch.id).filter(
        ProductionBatch.id == normalized,
        ProductionBatch.production_order_id == po.id,
    ).first()
    if not exists:
        raise HTTPException(404, "Production batch not found for this production order")
    return normalized


def _context_work_order(db: DbSession, source_wo: WorkOrder, operation: str) -> WorkOrder | None:
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == source_wo.production_order_id,
        WorkOrder.operation == operation,
    )
    if source_wo.production_batch_id is None:
        qry = qry.filter(WorkOrder.production_batch_id.is_(None))
    else:
        qry = qry.filter(WorkOrder.production_batch_id == source_wo.production_batch_id)
    return qry.order_by(WorkOrder.id.asc()).first()


def _gate_record_submission(wo: WorkOrder, user) -> None:
    """Reject record submission when the WO is blocked or past deadline.

    Users with `production.override_deadline` (e.g. Management / Admin) bypass
    the deadline check. Blocked WOs always require an explicit unblock first.
    """
    from app.core.deps import is_admin, user_permissions
    if wo.is_blocked:
        raise HTTPException(409, f"Work order is blocked: {wo.block_reason or 'no reason given'}")
    deadline = as_utc(wo.deadline)
    if deadline and wo.status not in ("completed", "rejected", "cancelled"):
        if deadline < datetime.now(timezone.utc):
            perms = user_permissions(user)
            if not (is_admin(user) or "production.override_deadline" in perms):
                raise HTTPException(
                    409,
                    f"Work order is past its deadline ({deadline.isoformat()}). "
                    "Management override required.",
                )


def _flow_committed_today(db: DbSession, flow_id: int, now: datetime) -> int:
    """Approximate today's committed load for a sewing line."""
    committed = 0

    # 1) Active split assignments contribute daily allocation.
    assignments = db.query(SewingAssignment).filter(
        SewingAssignment.sewing_flow_id == flow_id,
        SewingAssignment.status.in_(["planned", "in_progress"]),
    ).join(
        WorkOrder, WorkOrder.id == SewingAssignment.work_order_id,
    ).filter(
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    ).all()
    for a in assignments:
        remaining_qty = max(0, int(a.quantity or 0) - int(a.completed_qty or 0))
        if remaining_qty <= 0:
            continue
        a_start = as_utc(a.planned_start)
        a_end = as_utc(a.planned_end)
        if not a_start or not a_end:
            continue
        if a_start <= now <= a_end:
            days = max(1.0, (a_end - a_start).total_seconds() / 86400.0)
            committed += round(remaining_qty / days)

    # 2) Directly assigned sewing WOs (without split assignments) count fully.
    direct_wos = db.query(WorkOrder).filter(
        WorkOrder.sewing_flow_id == flow_id,
        WorkOrder.operation == "sewing",
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    ).all()
    for w in direct_wos:
        has_split = db.query(SewingAssignment.id).filter(
            SewingAssignment.work_order_id == w.id,
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).first()
        if has_split:
            continue
        remaining = max(0, int(w.planned_output_qty or 0) - int(w.passed_qty or 0))
        committed += remaining

    return int(committed)


# ===== Production Orders =====
@router.get("/production-orders", response_model=list[ProductionOrderOut])
def list_pos(db: DbSession, _: CurrentUser, status: str | None = None, production_type: str | None = None, page: int = 1, page_size: int = 50):
    qry = db.query(ProductionOrder)
    if status: qry = qry.filter(ProductionOrder.status == status)
    if production_type: qry = qry.filter(ProductionOrder.production_type == production_type)
    return qry.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.post("/production-orders", response_model=ProductionOrderDetail, status_code=201)
def create_po(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    po = create_production_order(
        db,
        production_type=payload.production_type,
        model_id=payload.model_id,
        sales_order_id=payload.sales_order_id,
        collection_id=payload.collection_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    if payload.batches:
        create_production_batches(db, po.id, [b.model_dump() for b in payload.batches])
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    include_printing = any(bool(i.printing_required) for i in (so.items or [])) if so else False
    create_work_orders(db, po.id, include_printing=include_printing)
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no})
    db.commit(); db.refresh(po)
    return po


@router.get("/production-orders/{pid}", response_model=ProductionOrderDetail)
def get_po(pid: int, db: DbSession, _: CurrentUser):
    po = db.query(ProductionOrder).options(
        joinedload(ProductionOrder.batches),
        joinedload(ProductionOrder.items),
        joinedload(ProductionOrder.work_orders),
    ).filter(ProductionOrder.id == pid).first()
    if not po: raise HTTPException(404, "Production order not found")
    return po


@router.patch("/production-orders/{pid}", response_model=ProductionOrderOut)
def update_po(pid: int, payload: dict, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    po = db.get(ProductionOrder, pid)
    if not po: raise HTTPException(404, "Production order not found")
    for k, v in payload.items():
        if hasattr(po, k):
            setattr(po, k, v)
    log_action(db, current, "update", "ProductionOrder", po.id)
    db.commit(); db.refresh(po)
    return po


@router.post("/production-orders/{pid}/create-work-orders")
def create_wos(pid: int, db: DbSession, current: User = Depends(require_permissions("planning.production", "*")), include_printing: bool = False):
    wos = create_work_orders(db, pid, include_printing=include_printing)
    log_action(db, current, "create_work_orders", "ProductionOrder", pid, new_value={"count": len(wos)})
    db.commit()
    return {"created": [{"id": w.id, "operation": w.operation} for w in wos]}


# Operation order matters for deadline backfill â€” earlier ops finish earlier.
_OP_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
# Default share of total duration consumed by each stage (rough industry mix).
_OP_DURATION_SHARE = {
    "cutting": 0.20, "printing": 0.10, "sewing": 0.45,
    "packaging": 0.15, "storage_transfer": 0.10,
}


@router.post("/production-orders/{pid}/cascade-deadlines")
def cascade_deadlines(pid: int, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    """Distribute the PO deadline backwards across each work order's deadline.

    If the model has a non-zero `sam_minutes`, sewing duration is computed from
    SAM * quantity. Other stages fill the remaining horizon proportionally.
    Otherwise the static 20/10/45/15/10 share is used.
    """
    from app.models import Model as ModelEntity  # local import to avoid cycles

    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")
    if not po.deadline:
        raise HTTPException(400, "Set a Production-Order deadline first")

    end = as_utc(po.deadline)
    start = as_utc(po.start_date) or (end - timedelta(days=30))
    now = datetime.now(timezone.utc)
    # If no explicit start_date is set, avoid generating stage deadlines in the past.
    if po.start_date is None and start < now < end:
        start = now
    if start >= end:
        raise HTTPException(400, "start_date must be before deadline")

    model_obj = db.get(ModelEntity, po.model_id)
    sam = float(model_obj.sam_minutes) if model_obj else 0.0
    qty = int(po.planned_quantity or 0)

    def _per_op_seconds(total_seconds: float, units: int) -> dict[str, float]:
        if sam > 0 and units > 0:
            # Sewing: SAM * qty minutes, capped at 70% of the available horizon.
            sew_seconds = min(total_seconds * 0.7, sam * units * 60.0)
            other_seconds = max(0.0, total_seconds - sew_seconds)
            others = {op: s for op, s in _OP_DURATION_SHARE.items() if op != "sewing"}
            s_sum = sum(others.values()) or 1.0
            out = {op: other_seconds * (s / s_sum) for op, s in others.items()}
            out["sewing"] = sew_seconds
            return out
        return {op: total_seconds * _OP_DURATION_SHARE.get(op, 0.2) for op in _OP_SEQUENCE}

    batches = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.production_order_id == pid)
        .order_by(ProductionBatch.batch_index.asc(), ProductionBatch.id.asc())
        .all()
    )
    batch_map = {b.id: b for b in batches}
    all_wos = db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all()
    groups: dict[int | None, list[WorkOrder]] = {}
    for w in all_wos:
        groups.setdefault(w.production_batch_id, []).append(w)

    updates: list[dict] = []
    for batch_id, wos in groups.items():
        batch = batch_map.get(batch_id) if batch_id is not None else None
        group_end = as_utc(batch.deadline) if batch and batch.deadline else end
        group_start = as_utc(batch.start_date) if batch and batch.start_date else start
        if (batch is None or batch.start_date is None) and po.start_date is None and group_start < now < group_end:
            group_start = now
        if group_start >= group_end:
            group_start = group_end - timedelta(minutes=1)

        group_qty = int(batch.planned_quantity or 0) if batch else max(0, qty)
        total_seconds = max(60.0, (group_end - group_start).total_seconds())
        per_op = _per_op_seconds(total_seconds, group_qty)
        by_op = {w.operation: w for w in wos}

        cursor = group_start
        for op in _OP_SEQUENCE:
            wo = by_op.get(op)
            if not wo:
                continue
            cursor = cursor + timedelta(seconds=per_op.get(op, 0))
            deadline = min(cursor, group_end)
            wo.deadline = deadline
            updates.append({
                "work_order_id": wo.id,
                "operation": op,
                "batch_id": batch_id,
                "deadline": deadline.isoformat(),
            })

    log_action(
        db,
        current,
        "cascade_deadlines",
        "ProductionOrder",
        pid,
        new_value={"updates": updates, "sam_minutes": sam, "qty": qty},
    )
    db.commit()
    return {"updates": updates, "sam_minutes": sam}


@router.post("/production-orders/{pid}/admin-repair-totals")
def admin_repair_totals(pid: int, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    """Admin recovery tool:
    Rebuild WO counters from source records and clamp passed/output to planned qty.
    Useful when duplicate submissions inflated stage totals.
    """
    if not is_admin(current):
        raise HTTPException(403, "Admin only action")

    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")

    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all()
    if any(w.production_batch_id is not None for w in work_orders):
        raise HTTPException(400, "Admin repair totals is not available for batched production orders yet")
    by_op = {w.operation: w for w in work_orders}
    now = datetime.now(timezone.utc)

    def _clamp_pass(planned: int, value: int) -> int:
        return max(0, min(max(0, int(planned or 0)), max(0, int(value or 0))))

    def _set_wo(wo: WorkOrder, *, input_qty: int, output_qty: int, passed_qty: int, failed_qty: int, rework_qty: int | None = None):
        before = {
            "actual_input_qty": int(wo.actual_input_qty or 0),
            "actual_output_qty": int(wo.actual_output_qty or 0),
            "passed_qty": int(wo.passed_qty or 0),
            "failed_qty": int(wo.failed_qty or 0),
            "rework_qty": int(wo.rework_qty or 0),
            "status": wo.status,
        }
        wo.actual_input_qty = max(0, int(input_qty or 0))
        wo.actual_output_qty = max(0, int(output_qty or 0))
        wo.passed_qty = max(0, int(passed_qty or 0))
        wo.failed_qty = max(0, int(failed_qty or 0))
        if rework_qty is not None:
            wo.rework_qty = max(0, int(rework_qty or 0))

        if wo.status not in ("cancelled", "rejected"):
            planned = max(0, int(wo.planned_output_qty or 0))
            if planned > 0 and wo.passed_qty >= planned:
                if wo.status != "completed":
                    wo.status = "completed"
                if not wo.end_time:
                    wo.end_time = now
            elif wo.passed_qty > 0 and wo.status in ("waiting", "pending", "collected", "new", "planning"):
                wo.status = "in_progress"
                if not wo.start_time:
                    wo.start_time = now

        after = {
            "actual_input_qty": int(wo.actual_input_qty or 0),
            "actual_output_qty": int(wo.actual_output_qty or 0),
            "passed_qty": int(wo.passed_qty or 0),
            "failed_qty": int(wo.failed_qty or 0),
            "rework_qty": int(wo.rework_qty or 0),
            "status": wo.status,
        }
        return before, after

    changes: list[dict] = []

    cut_wo = by_op.get("cutting")
    if cut_wo:
        cut_input, cut_passed, cut_failed = db.query(
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        ).filter(CuttingRecord.work_order_id == cut_wo.id).one()
        planned = int(cut_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(cut_passed or 0))
        output = passed
        before, after = _set_wo(
            cut_wo,
            input_qty=max(int(cut_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(cut_failed or 0),
            rework_qty=int(cut_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": cut_wo.id, "operation": "cutting", "before": before, "after": after})

    prt_wo = by_op.get("printing")
    if prt_wo:
        prt_input, prt_passed, prt_failed = db.query(
            func.coalesce(func.sum(PrintingRecord.input_qty), 0),
            func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
        ).filter(PrintingRecord.work_order_id == prt_wo.id).one()
        planned = int(prt_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(prt_passed or 0))
        output = passed
        before, after = _set_wo(
            prt_wo,
            input_qty=max(int(prt_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(prt_failed or 0),
            rework_qty=int(prt_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": prt_wo.id, "operation": "printing", "before": before, "after": after})

    sew_wo = by_op.get("sewing")
    if sew_wo:
        sew_input, sew_passed, sew_failed, sew_rework = db.query(
            func.coalesce(func.sum(SewingRecord.input_qty), 0),
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
            func.coalesce(func.sum(SewingRecord.failed_qty), 0),
            func.coalesce(func.sum(SewingRecord.rework_qty), 0),
        ).filter(SewingRecord.work_order_id == sew_wo.id).one()
        planned = int(sew_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(sew_passed or 0))
        output = passed
        before, after = _set_wo(
            sew_wo,
            input_qty=max(int(sew_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(sew_failed or 0),
            rework_qty=int(sew_rework or 0),
        )
        if before != after:
            changes.append({"work_order_id": sew_wo.id, "operation": "sewing", "before": before, "after": after})

    pkg_wo = by_op.get("packaging")
    if pkg_wo:
        pkg_input, rec_packed, pkg_failed = db.query(
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
            func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
        ).filter(PackagingRecord.work_order_id == pkg_wo.id).one()

        packages_packed = db.query(func.coalesce(func.sum(Package.total_quantity), 0)).filter(
            Package.production_order_id == pid,
            Package.status.in_(["packed", "received_in_storage", "reserved", "shipped", "delivered"]),
        ).scalar() or 0

        source_packed = int(packages_packed or 0) if int(packages_packed or 0) > 0 else int(rec_packed or 0)
        planned = int(pkg_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, source_packed)
        output = passed
        before, after = _set_wo(
            pkg_wo,
            input_qty=max(int(pkg_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(pkg_failed or 0),
            rework_qty=int(pkg_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({
                "work_order_id": pkg_wo.id,
                "operation": "packaging",
                "source": "packages" if int(packages_packed or 0) > 0 else "packaging_records",
                "before": before,
                "after": after,
            })

    stg_wo = by_op.get("storage_transfer")
    if stg_wo:
        received_total = db.query(func.coalesce(func.sum(Package.total_quantity), 0)).filter(
            Package.production_order_id == pid,
            Package.status.in_(["received_in_storage", "reserved", "shipped", "delivered"]),
        ).scalar() or 0
        planned = int(stg_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(received_total or 0))
        output = passed
        before, after = _set_wo(
            stg_wo,
            input_qty=passed,
            output_qty=output,
            passed_qty=passed,
            failed_qty=0,
            rework_qty=int(stg_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": stg_wo.id, "operation": "storage_transfer", "before": before, "after": after})

    sync_production_order_status(db, pid)
    log_action(db, current, "admin_repair_totals", "ProductionOrder", pid, new_value={"changes": changes})
    db.commit()

    return {"production_order_id": pid, "changed_count": len(changes), "changes": changes}


# ===== Work Orders =====
@router.get("/work-orders", response_model=list[WorkOrderOut])
def list_wos(
    db: DbSession,
    _: CurrentUser,
    department_id: int | None = None,
    status: str | None = None,
    production_order_id: int | None = None,
    operation: str | None = None,
    only_active: bool = False,
    unassigned_flow: bool = False,
):
    qry = db.query(WorkOrder)
    if department_id: qry = qry.filter(WorkOrder.department_id == department_id)
    if status: qry = qry.filter(WorkOrder.status == status)
    if production_order_id: qry = qry.filter(WorkOrder.production_order_id == production_order_id)
    if operation: qry = qry.filter(WorkOrder.operation == operation)
    if only_active: qry = qry.filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
    if unassigned_flow:
        if not operation:
            qry = qry.filter(WorkOrder.operation == "sewing")
        qry = qry.filter(WorkOrder.sewing_flow_id.is_(None))
    return qry.order_by(WorkOrder.id.desc()).all()


@router.get("/work-orders/{wid}", response_model=WorkOrderOut)
def get_wo(wid: int, db: DbSession, _: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    return wo


@router.patch("/work-orders/{wid}", response_model=WorkOrderOut)
def update_wo(wid: int, payload: WorkOrderUpdate, db: DbSession, current: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    changes = payload.model_dump(exclude_unset=True)

    if wo.operation == "sewing" and "sewing_flow_id" in changes and changes["sewing_flow_id"]:
        target_flow = db.get(SewingFlow, int(changes["sewing_flow_id"]))
        if not target_flow:
            raise HTTPException(404, "Sewing flow not found")
        now = datetime.now(timezone.utc)
        committed = _flow_committed_today(db, target_flow.id, now)
        own_remaining = max(0, int(wo.planned_output_qty or 0) - int(wo.passed_qty or 0))
        if wo.sewing_flow_id == target_flow.id:
            has_split = db.query(SewingAssignment.id).filter(
                SewingAssignment.work_order_id == wo.id,
                SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
            ).first()
            if not has_split:
                committed = max(0, committed - own_remaining)
        projected = committed + own_remaining
        if int(target_flow.capacity_per_day or 0) > 0 and projected > int(target_flow.capacity_per_day):
            raise HTTPException(
                409,
                f"Capacity full: {target_flow.code} daily load would be {projected} vs capacity {target_flow.capacity_per_day}",
            )

    previous_assignee = wo.assigned_to
    for k, v in changes.items():
        setattr(wo, k, v)
    # If assignment changed, notify the new assignee so they know they have a new job.
    if "assigned_to" in changes and wo.assigned_to and wo.assigned_to != previous_assignee:
        from app.services.notifications import notify
        notify(
            db, user_id=wo.assigned_to,
            title=f"New job: {wo.operation} work order #{wo.id}",
            message=f"You were assigned to work order #{wo.id} ({wo.operation}, status: {wo.status}).",
            link=f"/work-orders/{wo.id}/{wo.operation}",
        )
    log_action(db, current, "update", "WorkOrder", wo.id, new_value=changes)
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/start", response_model=WorkOrderOut)
def start_wo(wid: int, db: DbSession, current: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    wo.status = "in_progress"
    wo.start_time = datetime.now(timezone.utc)
    log_action(db, current, "start", "WorkOrder", wo.id)
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/collect", response_model=WorkOrderOut)
def collect_printing_wo(
    wid: int,
    payload: PrintingCollectIn,
    db: DbSession,
    current: User = Depends(require_permissions("printing.records", "planning.production", "*")),
):
    """Master intake for printing queue: confirm collection and set print ETA."""
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "printing":
        raise HTTPException(400, "Collect action is only allowed for printing work orders")
    if wo.status in ("in_progress", "completed", "rejected", "cancelled"):
        raise HTTPException(409, f"Cannot collect work order in status '{wo.status}'")

    wo.status = "collected"
    wo.deadline = payload.deadline
    if payload.notes is not None:
        wo.notes = payload.notes

    log_action(
        db,
        current,
        "collect",
        "WorkOrder",
        wo.id,
        new_value={
            "status": wo.status,
            "deadline": wo.deadline,
            "notes": wo.notes,
        },
    )
    db.commit()
    db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/complete", response_model=WorkOrderOut)
def complete_wo(wid: int, db: DbSession, current: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    wo.status = "completed"
    wo.end_time = datetime.now(timezone.utc)
    log_action(db, current, "complete", "WorkOrder", wo.id)
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/split-batches")
def split_cutting_work_order_batches(
    wid: int,
    payload: SplitWorkOrderBatchesIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "planning.production", "*")),
):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Only cutting work orders can be split into batches")
    if wo.production_batch_id is not None:
        raise HTTPException(409, "This work order is already assigned to a batch")

    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    existing_batches = db.query(ProductionBatch.id).filter(ProductionBatch.production_order_id == po.id).first()
    if existing_batches:
        raise HTTPException(409, "Production order already has batches")

    rows = payload.batches or []
    if not rows:
        raise HTTPException(400, "Provide at least one batch")
    if any(int(row.planned_quantity or 0) <= 0 for row in rows):
        raise HTTPException(400, "Each batch quantity must be greater than zero")
    total = sum(int(row.planned_quantity or 0) for row in rows)
    if total != int(po.planned_quantity or 0):
        raise HTTPException(
            400,
            f"Batch quantities ({total}) must match production planned quantity ({int(po.planned_quantity or 0)})",
        )

    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()
    work_order_ids = [w.id for w in work_orders]
    if not work_order_ids:
        raise HTTPException(400, "No work orders found for this production order")

    has_activity = (
        db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(PrintingRecord.id).filter(PrintingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(SewingRecord.id).filter(SewingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(PackagingRecord.id).filter(PackagingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(SewingAssignment.id).filter(SewingAssignment.work_order_id.in_(work_order_ids)).first()
        or db.query(QualityCheck.id).filter(QualityCheck.work_order_id.in_(work_order_ids)).first()
        or db.query(WasteRecord.id).filter(WasteRecord.work_order_id.in_(work_order_ids)).first()
    )
    if has_activity:
        raise HTTPException(409, "Cannot split: this order already has production activity records")

    batch_payload = [row.model_dump() for row in rows]
    created_batches = create_production_batches(db, po.id, batch_payload)

    log_action(
        db,
        current,
        "split_into_batches",
        "ProductionOrder",
        po.id,
        new_value={
            "batch_count": len(created_batches),
            "total_quantity": total,
            "work_order_id": wo.id,
            "kept_single_work_order": True,
        },
    )
    db.commit()
    return {
        "production_order_id": po.id,
        "batch_count": len(created_batches),
        "work_order_id": wo.id,
        "kept_single_work_order": True,
    }


@router.get("/work-orders/{wid}/cutting-batch-progress")
def cutting_batch_progress(wid: int, db: DbSession, _: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Work order is not a cutting operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            CuttingRecord.production_batch_id,
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        )
        .filter(CuttingRecord.work_order_id == wo.id)
        .group_by(CuttingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, cut_sum, passed_sum, defective_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "cut_pieces": int(cut_sum or 0),
            "passed_pieces": int(passed_sum or 0),
            "defective_pieces": int(defective_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_pieces", 0))
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "cut_pieces": int(totals.get("cut_pieces", 0)),
            "passed_pieces": passed,
            "defective_pieces": int(totals.get("defective_pieces", 0)),
            "remaining_quantity": max(0, planned - passed),
            "progress_pct": round((100.0 * passed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/printing-batch-progress")
def printing_batch_progress(wid: int, db: DbSession, _: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "printing":
        raise HTTPException(400, "Work order is not a printing operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            PrintingRecord.production_batch_id,
            func.coalesce(func.sum(PrintingRecord.input_qty), 0),
            func.coalesce(func.sum(PrintingRecord.printed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
        )
        .filter(PrintingRecord.work_order_id == wo.id)
        .group_by(PrintingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, printed_sum, passed_sum, rejected_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "printed_qty": int(printed_sum or 0),
            "passed_qty": int(passed_sum or 0),
            "rejected_qty": int(rejected_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_qty", 0))
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "printed_qty": int(totals.get("printed_qty", 0)),
            "passed_qty": passed,
            "rejected_qty": int(totals.get("rejected_qty", 0)),
            "remaining_quantity": max(0, planned - passed),
            "progress_pct": round((100.0 * passed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/sewing-batch-progress")
def sewing_batch_progress(wid: int, db: DbSession, _: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing":
        raise HTTPException(400, "Work order is not a sewing operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            SewingRecord.production_batch_id,
            func.coalesce(func.sum(SewingRecord.input_qty), 0),
            func.coalesce(func.sum(SewingRecord.sewn_qty), 0),
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
            func.coalesce(func.sum(SewingRecord.failed_qty), 0),
            func.coalesce(func.sum(SewingRecord.rework_qty), 0),
            func.coalesce(func.sum(SewingRecord.rejected_qty), 0),
        )
        .filter(SewingRecord.work_order_id == wo.id)
        .group_by(SewingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, sewn_sum, passed_sum, failed_sum, rework_sum, rejected_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "sewn_qty": int(sewn_sum or 0),
            "passed_qty": int(passed_sum or 0),
            "failed_qty": int(failed_sum or 0),
            "rework_qty": int(rework_sum or 0),
            "rejected_qty": int(rejected_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_qty", 0))
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "sewn_qty": int(totals.get("sewn_qty", 0)),
            "passed_qty": passed,
            "failed_qty": int(totals.get("failed_qty", 0)),
            "rework_qty": int(totals.get("rework_qty", 0)),
            "rejected_qty": int(totals.get("rejected_qty", 0)),
            "remaining_quantity": max(0, planned - passed),
            "progress_pct": round((100.0 * passed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/packaging-batch-progress")
def packaging_batch_progress(wid: int, db: DbSession, _: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "packaging":
        raise HTTPException(400, "Work order is not a packaging operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            PackagingRecord.production_batch_id,
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
            func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
        )
        .filter(PackagingRecord.work_order_id == wo.id)
        .group_by(PackagingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, packed_sum, damaged_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "packed_qty": int(packed_sum or 0),
            "damaged_qty": int(damaged_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        packed = int(totals.get("packed_qty", 0))
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "packed_qty": packed,
            "damaged_qty": int(totals.get("damaged_qty", 0)),
            "remaining_quantity": max(0, planned - packed),
            "progress_pct": round((100.0 * packed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


# ===== Cutting =====
@router.post("/cutting/records", status_code=201)
def post_cutting(payload: CuttingRecordIn, db: DbSession, current: User = Depends(require_permissions("cutting.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting": raise HTTPException(400, "Work order is not a cutting operation")
    _gate_record_submission(wo, current)
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="cutting",
    )

    rec = CuttingRecord(
        work_order_id=payload.work_order_id,
        production_batch_id=batch_id,
        fabric_batch_id=payload.fabric_batch_id,
        input_quantity=payload.input_quantity,
        input_unit=payload.input_unit,
        cut_pieces=payload.cut_pieces,
        passed_pieces=payload.passed_pieces,
        defective_pieces=payload.defective_pieces,
        waste_quantity=payload.waste_quantity,
        waste_unit=payload.waste_unit,
        bundle_count=len(payload.bundles or []),
        total_bundled_quantity=sum(int(b.get("quantity", 0)) * int(b.get("count", 1)) for b in (payload.bundles or [])),
        operator_id=payload.operator_id or current.id,
        notes=payload.notes,
    )
    db.add(rec); db.flush()

    # Update work order quantities
    wo.actual_input_qty += int(payload.cut_pieces or 0)
    wo.actual_output_qty += int(payload.passed_pieces or 0)
    wo.passed_qty += int(payload.passed_pieces or 0)
    wo.failed_qty += int(payload.defective_pieces or 0)
    if payload.fabric_batch_id and float(payload.input_quantity or 0) > 0:
        consume_stock_batch(
            db,
            batch_id=payload.fabric_batch_id,
            quantity=float(payload.input_quantity or 0),
            unit=payload.input_unit,
            reference_type="CuttingRecord",
            reference_id=rec.id,
            user_id=current.id,
        )
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=payload.fabric_batch_id,
        waste_type="cutting_waste",
        quantity=float(payload.waste_quantity or 0),
        unit=payload.waste_unit,
        reason="Auto-created from cutting record",
        created_by=current.id,
    )

    # Create bundles for the plan
    so_id = po.sales_order_id if po else None
    created_bundles = []
    to_printing = 0
    to_sewing = 0
    for spec in (payload.bundles or []):
        count = int(spec.get("count", 1))
        qty = int(spec.get("quantity", 0))
        for _ in range(count):
            next_code = "PRT" if spec.get("next") == "printing" else "SEW"
            b = create_bundle(
                db,
                production_order_id=wo.production_order_id,
                model_id=po.model_id,
                color=spec["color"],
                size=spec["size"],
                quantity=qty,
                sales_order_id=so_id,
                next_department_code=next_code,
                user_id=current.id,
            )
            created_bundles.append({"id": b.id, "bundle_no": b.bundle_no, "barcode": b.barcode})
            if next_code == "PRT":
                to_printing += 1
            else:
                to_sewing += 1

    advance_workflow(db, wo, trigger_output_qty=int(payload.passed_pieces or 0))
    if to_printing:
        notify_department(
            db,
            department_code="PRT",
            title="Incoming cutting bundles",
            message=f"{to_printing} bundle(s) ready from WO #{wo.id}.",
            link="/bundles/scan/printing",
        )
    if to_sewing:
        notify_department(
            db,
            department_code="SEW",
            title="Incoming cutting bundles",
            message=f"{to_sewing} bundle(s) ready from WO #{wo.id}.",
            link="/bundles/scan/sewing",
        )

    log_action(db, current, "create", "CuttingRecord", rec.id, new_value={"bundles": len(created_bundles)})
    db.commit(); db.refresh(rec)
    return {"id": rec.id, "bundles": created_bundles}


@router.get("/cutting/records/{rid}")
def get_cutting(rid: int, db: DbSession, _: CurrentUser):
    r = db.get(CuttingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id,
        "production_batch_id": r.production_batch_id,
        "work_order_id": r.work_order_id,
        "fabric_batch_id": r.fabric_batch_id,
        "input_quantity": float(r.input_quantity), "cut_pieces": r.cut_pieces, "passed_pieces": r.passed_pieces,
        "defective_pieces": r.defective_pieces, "waste_quantity": float(r.waste_quantity),
        "bundle_count": r.bundle_count, "total_bundled_quantity": r.total_bundled_quantity,
        "operator_id": r.operator_id, "notes": r.notes,
    }


# ===== Printing =====
@router.post("/printing/records", status_code=201)
def post_printing(payload: PrintingRecordIn, db: DbSession, current: User = Depends(require_permissions("printing.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "printing": raise HTTPException(400, "Work order is not a printing operation")
    if wo.status in ("new", "planning", "waiting", "ready", "pending", "paused"):
        raise HTTPException(
            409,
            "Printing work order must be collected first. Set status to 'collected' and add a deadline.",
        )
    if wo.status == "collected":
        wo.status = "in_progress"
        if not wo.start_time:
            wo.start_time = datetime.now(timezone.utc)
    _gate_record_submission(wo, current)
    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="printing",
    )

    if batch_id is not None:
        cut_wo = _context_work_order(db, wo, "cutting")
        upstream_passed = 0
        if cut_wo:
            upstream_passed = int(
                db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0))
                .filter(
                    CuttingRecord.work_order_id == cut_wo.id,
                    CuttingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        current_input = int(
            db.query(func.coalesce(func.sum(PrintingRecord.input_qty), 0))
            .filter(
                PrintingRecord.work_order_id == wo.id,
                PrintingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        if next_total > upstream_passed:
            raise HTTPException(
                400,
                f"Printing input {next_total} exceeds cutting passed {upstream_passed} for this batch",
            )

    rec_data = payload.model_dump()
    rec_data["production_batch_id"] = batch_id
    rec = PrintingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.rejected_qty
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="printing_reject",
        quantity=float(payload.rejected_qty or 0),
        unit="pcs",
        reason=payload.defect_reason or "Auto-created from printing record",
        created_by=current.id,
    )
    advance_workflow(db, wo, trigger_output_qty=int(payload.passed_qty or 0))
    if int(payload.passed_qty or 0) > 0:
        sew_wo = _context_work_order(db, wo, "sewing")
        notify_department(
            db,
            department_code="SEW",
            title="Incoming printed pieces",
            message=f"WO #{wo.id} passed {payload.passed_qty} pcs.",
            link=f"/work-orders/{sew_wo.id}/sewing" if sew_wo else "/bundles/scan/sewing",
        )
    log_action(db, current, "create", "PrintingRecord", rec.id, new_value={"work_order_id": wo.id})
    db.commit(); db.refresh(rec)
    return {"id": rec.id}


@router.get("/printing/records/{rid}")
def get_printing(rid: int, db: DbSession, _: CurrentUser):
    r = db.get(PrintingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id, "work_order_id": r.work_order_id,
        "production_batch_id": r.production_batch_id,
        "input_qty": r.input_qty, "printed_qty": r.printed_qty,
        "passed_qty": r.passed_qty, "rejected_qty": r.rejected_qty,
        "defect_reason": r.defect_reason, "print_type": r.print_type,
        "operator_id": r.operator_id, "notes": r.notes,
    }


# ===== Sewing =====
@router.post("/sewing/records", status_code=201)
def post_sewing(payload: SewingRecordIn, db: DbSession, current: User = Depends(require_permissions("sewing.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing": raise HTTPException(400, "Work order is not a sewing operation")
    _gate_record_submission(wo, current)
    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="sewing",
    )

    # Rule: sewing cannot receive more than cutting/printing passed
    upstream_passed = 0
    cut_wo = _context_work_order(db, wo, "cutting")
    prt_wo = _context_work_order(db, wo, "printing")
    if batch_id is not None:
        printing_passed = 0
        cutting_passed = 0
        if prt_wo:
            printing_passed = int(
                db.query(func.coalesce(func.sum(PrintingRecord.passed_qty), 0))
                .filter(
                    PrintingRecord.work_order_id == prt_wo.id,
                    PrintingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        if cut_wo:
            cutting_passed = int(
                db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0))
                .filter(
                    CuttingRecord.work_order_id == cut_wo.id,
                    CuttingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        upstream_passed = printing_passed if printing_passed > 0 else cutting_passed
        current_input = int(
            db.query(func.coalesce(func.sum(SewingRecord.input_qty), 0))
            .filter(
                SewingRecord.work_order_id == wo.id,
                SewingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        if next_total > upstream_passed:
            raise HTTPException(400, f"Sewing input {next_total} exceeds upstream passed {upstream_passed} for this batch")
    else:
        if prt_wo and prt_wo.passed_qty > 0:
            upstream_passed = prt_wo.passed_qty
        elif cut_wo:
            upstream_passed = cut_wo.passed_qty
        if upstream_passed and wo.actual_input_qty + payload.input_qty > upstream_passed:
            raise HTTPException(400, f"Sewing input {wo.actual_input_qty + payload.input_qty} exceeds upstream passed {upstream_passed}")

    assignment = None
    if payload.sewing_assignment_id:
        assignment = db.get(SewingAssignment, payload.sewing_assignment_id)
        if not assignment:
            raise HTTPException(404, "Sewing assignment not found")
        if assignment.work_order_id != wo.id:
            raise HTTPException(400, "Selected sewing assignment does not belong to this work order")
    elif payload.line_name:
        line_key = payload.line_name.strip().lower()
        if line_key:
            assignment = (
                db.query(SewingAssignment)
                .join(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
                .filter(SewingAssignment.work_order_id == wo.id)
                .filter(SewingAssignment.status.in_(["planned", "in_progress", "completed"]))
                .filter(func.lower(SewingFlow.code) == line_key)
                .order_by(SewingAssignment.id.desc())
                .first()
            )

    rec_data = payload.model_dump(exclude={"sewing_assignment_id"})
    rec_data["production_batch_id"] = batch_id
    rec = SewingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.failed_qty
    wo.rework_qty += payload.rework_qty
    consumed_total = int(payload.passed_qty or 0) + int(payload.failed_qty or 0) + int(payload.rejected_qty or 0)
    if assignment and consumed_total > 0:
        remaining = max(0, int(assignment.quantity or 0) - int(assignment.completed_qty or 0))
        consumed = min(remaining, consumed_total)
        if consumed > 0:
            assignment.completed_qty = int(assignment.completed_qty or 0) + consumed
        if assignment.completed_qty > 0 and assignment.status == "planned":
            assignment.status = "in_progress"
            if not assignment.actual_start:
                assignment.actual_start = datetime.now(timezone.utc)
        if assignment.completed_qty >= int(assignment.quantity or 0):
            assignment.completed_qty = int(assignment.quantity or 0)
            assignment.status = "completed"
            if not assignment.actual_start:
                assignment.actual_start = datetime.now(timezone.utc)
            assignment.actual_end = datetime.now(timezone.utc)
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="sewing_defect",
        quantity=float(payload.failed_qty or 0),
        unit="pcs",
        reason=payload.defect_reason or "Auto-created from sewing record",
        created_by=current.id,
    )
    advance_workflow(db, wo, trigger_output_qty=int(payload.passed_qty or 0))
    if int(payload.passed_qty or 0) > 0:
        pkg_wo = _context_work_order(db, wo, "packaging")
        notify_department(
            db,
            department_code="PKG",
            title="Awaiting packaging",
            message=f"WO #{wo.id} has {payload.passed_qty} pcs ready for packaging.",
            link=f"/work-orders/{pkg_wo.id}/packaging" if pkg_wo else "/packages",
        )
    log_action(db, current, "create", "SewingRecord", rec.id, new_value={"work_order_id": wo.id})
    db.commit(); db.refresh(rec)
    return {"id": rec.id}


@router.get("/sewing/records/{rid}")
def get_sewing(rid: int, db: DbSession, _: CurrentUser):
    r = db.get(SewingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id, "work_order_id": r.work_order_id,
        "production_batch_id": r.production_batch_id,
        "input_qty": r.input_qty, "sewn_qty": r.sewn_qty,
        "passed_qty": r.passed_qty, "failed_qty": r.failed_qty,
        "rework_qty": r.rework_qty, "rejected_qty": r.rejected_qty,
        "defect_reason": r.defect_reason, "line_name": r.line_name,
        "operator_id": r.operator_id, "notes": r.notes,
    }


# ===== Packaging =====
@router.post("/packaging/records", status_code=201)
def post_packaging(payload: PackagingRecordIn, db: DbSession, current: User = Depends(require_permissions("packaging.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "packaging": raise HTTPException(400, "Work order is not a packaging operation")
    _gate_record_submission(wo, current)
    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="packaging",
    )

    sew_wo = _context_work_order(db, wo, "sewing")
    if batch_id is not None:
        sewing_passed = 0
        if sew_wo:
            sewing_passed = int(
                db.query(func.coalesce(func.sum(SewingRecord.passed_qty), 0))
                .filter(
                    SewingRecord.work_order_id == sew_wo.id,
                    SewingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        current_input = int(
            db.query(func.coalesce(func.sum(PackagingRecord.input_qty), 0))
            .filter(
                PackagingRecord.work_order_id == wo.id,
                PackagingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        if next_total > sewing_passed:
            raise HTTPException(400, f"Packaging input {next_total} exceeds sewing passed {sewing_passed} for this batch")
    else:
        if sew_wo and wo.actual_input_qty + payload.input_qty > sew_wo.passed_qty:
            raise HTTPException(400, f"Packaging input {wo.actual_input_qty + payload.input_qty} exceeds sewing passed {sew_wo.passed_qty}")

    rec_data = payload.model_dump()
    rec_data["production_batch_id"] = batch_id
    rec = PackagingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.packed_qty
    wo.passed_qty += payload.packed_qty
    wo.failed_qty += payload.damaged_qty
    consume_packaging_materials_from_bom(
        db,
        production_order_id=wo.production_order_id,
        packed_qty=int(payload.packed_qty or 0),
        reference_type="PackagingRecord",
        reference_id=rec.id,
        user_id=current.id,
    )
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="packaging_damage",
        quantity=float(payload.damaged_qty or 0),
        unit="pcs",
        reason="Auto-created from packaging record",
        created_by=current.id,
    )
    advance_workflow(db, wo, trigger_output_qty=int(payload.packed_qty or 0))
    if int(payload.packed_qty or 0) > 0:
        notify_department(
            db,
            department_code="FGS",
            title="Packed goods ready",
            message=f"WO #{wo.id} packed {payload.packed_qty} pcs and is ready for storage intake.",
            link="/packages/scan",
        )
    log_action(db, current, "create", "PackagingRecord", rec.id, new_value={"work_order_id": wo.id})
    db.commit(); db.refresh(rec)
    return {"id": rec.id}


# ===== Quality =====
@router.post("/quality/checks", response_model=QualityCheckOut, status_code=201)
def post_quality(payload: QualityCheckIn, db: DbSession, current: CurrentUser):
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(404, "Work order not found")
    q = QualityCheck(**payload.model_dump(), checked_by=current.id, checked_at=datetime.now(timezone.utc))
    db.add(q); db.flush()
    log_action(db, current, "create", "QualityCheck", q.id)
    db.commit(); db.refresh(q)
    return q


@router.get("/quality/checks", response_model=list[QualityCheckOut])
def list_quality(db: DbSession, _: CurrentUser, work_order_id: int | None = None):
    qry = db.query(QualityCheck)
    if work_order_id: qry = qry.filter(QualityCheck.work_order_id == work_order_id)
    return qry.order_by(QualityCheck.id.desc()).all()
