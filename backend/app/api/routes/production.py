from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    ProductionOrder, WorkOrder, CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord,
    SalesOrder, QualityCheck, User, SewingFlow, SewingAssignment,
)
from app.schemas.production import (
    ProductionOrderIn, ProductionOrderOut, ProductionOrderDetail,
    WorkOrderOut, WorkOrderUpdate,
    CuttingRecordIn, PrintingRecordIn, SewingRecordIn, PackagingRecordIn,
    QualityCheckIn, QualityCheckOut,
)
from app.core.dt import as_utc
from app.services.audit import log_action
from app.services.production import create_production_order, create_work_orders
from app.services.bundles import create_bundle
from app.services.packages import create_package
from app.services.workflow import (
    advance_workflow,
    consume_packaging_materials_from_bom,
    consume_stock_batch,
    create_waste_record,
    notify_department,
)

router = APIRouter(tags=["production"])

_ACTIVE_WO_STATUSES = ("waiting", "ready", "in_progress", "paused", "new", "planning")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")


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
    ).all()
    for a in assignments:
        a_start = as_utc(a.planned_start)
        a_end = as_utc(a.planned_end)
        if not a_start or not a_end:
            continue
        if a_start <= now <= a_end:
            days = max(1.0, (a_end - a_start).total_seconds() / 86400.0)
            committed += round(a.quantity / days)

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
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    include_printing = any(bool(i.printing_required) for i in (so.items or [])) if so else False
    create_work_orders(db, po.id, include_printing=include_printing)
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no})
    db.commit(); db.refresh(po)
    return po


@router.get("/production-orders/{pid}", response_model=ProductionOrderDetail)
def get_po(pid: int, db: DbSession, _: CurrentUser):
    po = db.query(ProductionOrder).options(
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


# Operation order matters for deadline backfill — earlier ops finish earlier.
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
    SAM × quantity. Other stages fill the remaining horizon proportionally.
    Otherwise the static 20/10/45/15/10 share is used.
    """
    from app.models import Model as ModelEntity  # local import to avoid cycles
    po = db.get(ProductionOrder, pid)
    if not po: raise HTTPException(404, "Production order not found")
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
    total_seconds = (end - start).total_seconds()

    model_obj = db.get(ModelEntity, po.model_id)
    sam = float(model_obj.sam_minutes) if model_obj else 0.0
    qty = int(po.planned_quantity or 0)

    if sam > 0 and qty > 0:
        # Sewing: SAM × qty minutes, capped at 70% of total horizon.
        sew_seconds = min(total_seconds * 0.7, sam * qty * 60.0)
        other_seconds = max(0.0, total_seconds - sew_seconds)
        others = {op: s for op, s in _OP_DURATION_SHARE.items() if op != "sewing"}
        s_sum = sum(others.values()) or 1.0
        per_op = {op: other_seconds * (s / s_sum) for op, s in others.items()}
        per_op["sewing"] = sew_seconds
    else:
        per_op = {op: total_seconds * _OP_DURATION_SHARE.get(op, 0.2) for op in _OP_SEQUENCE}

    wos_by_op: dict[str, WorkOrder] = {}
    for w in db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all():
        wos_by_op[w.operation] = w

    cursor = start
    updates: list[dict] = []
    for op in _OP_SEQUENCE:
        wo = wos_by_op.get(op)
        if not wo:
            continue
        cursor = cursor + timedelta(seconds=per_op.get(op, 0))
        deadline = min(cursor, end)
        wo.deadline = deadline
        updates.append({"work_order_id": wo.id, "operation": op, "deadline": deadline.isoformat()})

    log_action(db, current, "cascade_deadlines", "ProductionOrder", pid, new_value={
        "updates": updates, "sam_minutes": sam, "qty": qty,
    })
    db.commit()
    return {"updates": updates, "sam_minutes": sam}


# ===== Work Orders =====
@router.get("/work-orders", response_model=list[WorkOrderOut])
def list_wos(db: DbSession, _: CurrentUser, department_id: int | None = None, status: str | None = None, production_order_id: int | None = None):
    qry = db.query(WorkOrder)
    if department_id: qry = qry.filter(WorkOrder.department_id == department_id)
    if status: qry = qry.filter(WorkOrder.status == status)
    if production_order_id: qry = qry.filter(WorkOrder.production_order_id == production_order_id)
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


@router.post("/work-orders/{wid}/complete", response_model=WorkOrderOut)
def complete_wo(wid: int, db: DbSession, current: CurrentUser):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    wo.status = "completed"
    wo.end_time = datetime.now(timezone.utc)
    log_action(db, current, "complete", "WorkOrder", wo.id)
    db.commit(); db.refresh(wo)
    return wo


# ===== Cutting =====
@router.post("/cutting/records", status_code=201)
def post_cutting(payload: CuttingRecordIn, db: DbSession, current: User = Depends(require_permissions("cutting.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting": raise HTTPException(400, "Work order is not a cutting operation")
    _gate_record_submission(wo, current)

    rec = CuttingRecord(
        work_order_id=payload.work_order_id,
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
    po = db.get(ProductionOrder, wo.production_order_id)
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
            link="/bundles/scan",
        )
    if to_sewing:
        notify_department(
            db,
            department_code="SEW",
            title="Incoming cutting bundles",
            message=f"{to_sewing} bundle(s) ready from WO #{wo.id}.",
            link="/bundles/scan",
        )

    log_action(db, current, "create", "CuttingRecord", rec.id, new_value={"bundles": len(created_bundles)})
    db.commit(); db.refresh(rec)
    return {"id": rec.id, "bundles": created_bundles}


@router.get("/cutting/records/{rid}")
def get_cutting(rid: int, db: DbSession, _: CurrentUser):
    r = db.get(CuttingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id, "work_order_id": r.work_order_id, "fabric_batch_id": r.fabric_batch_id,
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
    _gate_record_submission(wo, current)
    rec = PrintingRecord(**payload.model_dump(), )
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
        sew_wo = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == wo.production_order_id,
            WorkOrder.operation == "sewing",
        ).first()
        notify_department(
            db,
            department_code="SEW",
            title="Incoming printed pieces",
            message=f"WO #{wo.id} passed {payload.passed_qty} pcs.",
            link=f"/work-orders/{sew_wo.id}/sewing" if sew_wo else "/bundles/scan",
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

    # Rule: sewing cannot receive more than cutting/printing passed
    po_id = wo.production_order_id
    upstream_passed = 0
    cut_wo = db.query(WorkOrder).filter(WorkOrder.production_order_id == po_id, WorkOrder.operation == "cutting").first()
    prt_wo = db.query(WorkOrder).filter(WorkOrder.production_order_id == po_id, WorkOrder.operation == "printing").first()
    if prt_wo and prt_wo.passed_qty > 0:
        upstream_passed = prt_wo.passed_qty
    elif cut_wo:
        upstream_passed = cut_wo.passed_qty

    if upstream_passed and wo.actual_input_qty + payload.input_qty > upstream_passed:
        raise HTTPException(400, f"Sewing input {wo.actual_input_qty + payload.input_qty} exceeds upstream passed {upstream_passed}")

    rec = SewingRecord(**payload.model_dump())
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.failed_qty
    wo.rework_qty += payload.rework_qty
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
        pkg_wo = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == wo.production_order_id,
            WorkOrder.operation == "packaging",
        ).first()
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

    sew_wo = db.query(WorkOrder).filter(WorkOrder.production_order_id == wo.production_order_id, WorkOrder.operation == "sewing").first()
    if sew_wo and wo.actual_input_qty + payload.input_qty > sew_wo.passed_qty:
        raise HTTPException(400, f"Packaging input {wo.actual_input_qty + payload.input_qty} exceeds sewing passed {sew_wo.passed_qty}")

    rec = PackagingRecord(**payload.model_dump())
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
