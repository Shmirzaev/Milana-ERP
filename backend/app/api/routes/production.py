from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import joinedload

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import (
    ProductionOrder, WorkOrder, CuttingRecord, PrintingRecord, SewingRecord, PackagingRecord,
    SalesOrder, QualityCheck, User,
)
from app.schemas.production import (
    ProductionOrderIn, ProductionOrderOut, ProductionOrderDetail,
    WorkOrderOut, WorkOrderUpdate,
    CuttingRecordIn, PrintingRecordIn, SewingRecordIn, PackagingRecordIn,
    QualityCheckIn, QualityCheckOut,
)
from app.services.audit import log_action
from app.services.production import create_production_order, create_work_orders
from app.services.bundles import create_bundle
from app.services.packages import create_package

router = APIRouter(tags=["production"])


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

    Algorithm: anchor on the PO deadline as the *final* due date. Walk the
    operation sequence backwards, subtracting each stage's share of the total
    horizon (PO.start_date or 30 days back from deadline if not set).
    """
    po = db.get(ProductionOrder, pid)
    if not po: raise HTTPException(404, "Production order not found")
    if not po.deadline:
        raise HTTPException(400, "Set a Production-Order deadline first")

    end = po.deadline
    start = po.start_date or (end - timedelta(days=30))
    if start >= end:
        raise HTTPException(400, "start_date must be before deadline")
    total_days = (end - start).total_seconds() / 86400.0

    # Map operation -> WorkOrder for the present POs we already have
    wos_by_op: dict[str, WorkOrder] = {}
    for w in db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all():
        wos_by_op[w.operation] = w

    # Walk in sequence; each WO ends when its share has elapsed.
    cursor = start
    updates: list[dict] = []
    for op in _OP_SEQUENCE:
        wo = wos_by_op.get(op)
        if not wo:
            continue
        share = _OP_DURATION_SHARE.get(op, 0.2)
        cursor = cursor + timedelta(days=total_days * share)
        deadline = min(cursor, end)
        wo.deadline = deadline
        updates.append({"work_order_id": wo.id, "operation": op, "deadline": deadline.isoformat()})

    log_action(db, current, "cascade_deadlines", "ProductionOrder", pid, new_value={"updates": updates})
    db.commit()
    return {"updates": updates}


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

    # Create bundles for the plan
    po = db.get(ProductionOrder, wo.production_order_id)
    so_id = po.sales_order_id if po else None
    created_bundles = []
    for spec in (payload.bundles or []):
        count = int(spec.get("count", 1))
        qty = int(spec.get("quantity", 0))
        for _ in range(count):
            b = create_bundle(
                db,
                production_order_id=wo.production_order_id,
                model_id=po.model_id,
                color=spec["color"],
                size=spec["size"],
                quantity=qty,
                sales_order_id=so_id,
                next_department_code="PRT" if spec.get("next") == "printing" else "SEW",
                user_id=current.id,
            )
            created_bundles.append({"id": b.id, "bundle_no": b.bundle_no, "barcode": b.barcode})

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
    rec = PrintingRecord(**payload.model_dump(), )
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.rejected_qty
    log_action(db, current, "create", "PrintingRecord", None, new_value={"work_order_id": wo.id})
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
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.failed_qty
    wo.rework_qty += payload.rework_qty
    log_action(db, current, "create", "SewingRecord", None, new_value={"work_order_id": wo.id})
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

    sew_wo = db.query(WorkOrder).filter(WorkOrder.production_order_id == wo.production_order_id, WorkOrder.operation == "sewing").first()
    if sew_wo and wo.actual_input_qty + payload.input_qty > sew_wo.passed_qty:
        raise HTTPException(400, f"Packaging input {wo.actual_input_qty + payload.input_qty} exceeds sewing passed {sew_wo.passed_qty}")

    rec = PackagingRecord(**payload.model_dump())
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.packed_qty
    wo.passed_qty += payload.packed_qty
    wo.failed_qty += payload.damaged_qty
    log_action(db, current, "create", "PackagingRecord", None, new_value={"work_order_id": wo.id})
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
