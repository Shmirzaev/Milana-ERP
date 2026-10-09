"""Small, fail-closed workspace for individually scoped sewing bands."""
from datetime import datetime, timezone
import re
from typing import Annotated
from urllib.parse import parse_qs, urlparse
from fastapi import Header
from app.services.idempotency import replay_idempotent_response

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.core.deps import CurrentUser, DbSession, require_permissions
from app.models import Bundle, SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder
from app.schemas.production import SewingRecordIn
from app.services.audit import log_action
from app.services.sewing_band_progress import band_board
from app.services.sewing_scope import require_sewing_flow_access, sewing_line_factory_scope

router = APIRouter(prefix="/sewing-bands", tags=["sewing-bands"])


def own_band(db, current):
    flow = db.get(SewingFlow, current.sewing_band_id) if current.sewing_band_id else None
    if not flow or not flow.is_active:
        raise HTTPException(403, "A sewing band account is required")
    require_sewing_flow_access(current, flow)
    return flow


@router.get("")
def board(db: DbSession, current: User = Depends(require_permissions("sewing.workspace", "sewing.flows"))):
    sewing_line_factory_scope(current, "ECO")
    query = db.query(SewingFlow.id).filter(SewingFlow.factory_code == "ECO", SewingFlow.is_active.is_(True))
    if current.sewing_band_id:
        query = query.filter(SewingFlow.id == current.sewing_band_id)
    return band_board(db, [fid for fid, in query.all()])


@router.get("/orders")
def band_orders(db: DbSession, current: CurrentUser):
    """ERP floor presentation, bounded by the authenticated band's assignments."""
    from app.api.routes.inbox import _production_context_by_production_order, _material_payload_by_production_order
    flow = own_band(db, current)
    jobs = band_board(db, [flow.id])[0]["jobs"]
    po_ids = list({j["production_order_id"] for j in jobs})
    context = _production_context_by_production_order(db, po_ids)
    materials = _material_payload_by_production_order(db, po_ids)
    work_orders = {w.id: w for w in db.query(WorkOrder).filter(WorkOrder.id.in_([j["work_order_id"] for j in jobs])).all()} if jobs else {}
    return [{
        **context.get(j["production_order_id"], {}),
        **materials.get(j["production_order_id"], {}),
        **j,
        "sewing_assignment_id": j["id"],
        "operation": "sewing", "planned_output_qty": j["quantity"],
        "passed_qty": j["actual_qty"],
        "deadline": work_orders[j["work_order_id"]].deadline,
        "queueKind": "completed" if j["status"] == "completed" else "in_progress",
    } for j in jobs]


def scope_assignments(db, wo, batch_id):
    return db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id == wo.id,
        SewingAssignment.status.in_(("planned", "in_progress", "completed")),
        (SewingAssignment.production_batch_id == batch_id) | SewingAssignment.production_batch_id.is_(None),
    ).all()


def receipt_work(db, po_id, batch_id):
    query = db.query(WorkOrder).filter(WorkOrder.production_order_id == po_id, WorkOrder.operation == "sewing")
    wo = query.filter(WorkOrder.production_batch_id == batch_id).first() if batch_id else None
    wo = wo or query.filter(WorkOrder.production_batch_id.is_(None)).first()
    if not wo:
        raise HTTPException(409, "Sewing work order is not available")
    return wo


def check_claim(db, wo, batch_id, flow):
    assignments = scope_assignments(db, wo, batch_id)
    if any(a.sewing_flow_id != flow.id for a in assignments):
        raise HTTPException(409, "This work is assigned to another band; ask a manager to transfer it")
    if len(assignments) > 1:
        raise HTTPException(409, "This work has split assignments; a manager must receive it")
    if not assignments and wo.sewing_flow_id and wo.sewing_flow_id != flow.id:
        # A primary line on an assignment-managed order is only a display hint.
        if not db.query(SewingAssignment.id).filter(SewingAssignment.work_order_id == wo.id).first():
            raise HTTPException(409, "This order belongs to another band")
    if wo.status in ("completed", "cancelled") or any(a.status == "completed" or a.line_finished_at for a in assignments):
        raise HTTPException(409, "This sewing work is closed")
    return assignments[0] if assignments else None


@router.get("/receive-options")
def receive_options(db: DbSession, current: CurrentUser, q: str = ""):
    from app.api.routes.bundles import sewing_receive_options
    flow = own_band(db, current)
    rows = sewing_receive_options(db, current, q=q, limit=100, factory_code="ECO")
    result = []
    for row in rows:
        try:
            wo = receipt_work(db, row["production_order_id"], row["production_batch_id"])
            check_claim(db, wo, row["production_batch_id"], flow)
        except HTTPException as exc:
            if exc.status_code == 409:
                continue
            raise
        result.append(row)
    return result


class ReceiveIn(BaseModel):
    code: str | None = Field(default=None, max_length=2048)
    production_order_id: int | None = None
    production_batch_id: int | None = None


@router.post("/receive")
def receive(payload: ReceiveIn, db: DbSession, current: CurrentUser):
    from app.api.routes.bundles import _sewing_receive_eligible_filter
    from app.services.bundles import receive_many_at_sewing, verify_sewing_accessory_gate
    from app.services.bundles import find_bundle_by_scanned_code
    flow = own_band(db, current)
    if payload.code:
        batch_match = re.fullmatch(r"SEWING_BATCH:(\d+)", payload.code.strip(), re.IGNORECASE)
        batch_id = int(batch_match[1]) if batch_match else None
        parsed = urlparse(payload.code.strip())
        if parsed.path.endswith("/bundles/scan/sewing"):
            value = parse_qs(parsed.query).get("batch", [""])[0]
            if value.isdecimal() and int(value) > 0:
                batch_id = int(value)
        if batch_id:
            from app.models import ProductionBatch
            batch = db.get(ProductionBatch, batch_id)
            if not batch:
                raise HTTPException(404, "Batch not found")
            return receive(ReceiveIn(production_order_id=batch.production_order_id, production_batch_id=batch.id), db, current)
        scanned = find_bundle_by_scanned_code(db, payload.code.strip())
        if not scanned:
            raise HTTPException(404, "Bundle not found")
        po_id, batch_id = scanned.production_order_id, scanned.production_batch_id
        query = db.query(Bundle).filter(Bundle.id == scanned.id)
    elif payload.production_order_id:
        po_id, batch_id = payload.production_order_id, payload.production_batch_id
        query = db.query(Bundle).filter(Bundle.production_order_id == po_id, Bundle.production_batch_id == batch_id,
                                        Bundle.sewing_factory_code == "ECO", _sewing_receive_eligible_filter(db))
    else:
        raise HTTPException(422, "Scan a bundle or select a receiving batch")
    # Existing receipt services lock bundles before work orders. Keep that order.
    bundles = query.order_by(Bundle.id).populate_existing().with_for_update().all()
    if not bundles:
        raise HTTPException(409, "No bundles are waiting for receipt")
    if any(b.sewing_factory_code != "ECO" for b in bundles):
        raise HTTPException(403, "This bundle belongs to another factory")
    wo = receipt_work(db, po_id, batch_id)
    wo = db.query(WorkOrder).filter(WorkOrder.id == wo.id).populate_existing().with_for_update().one()
    assignment = check_claim(db, wo, batch_id, flow)
    if all(b.status == "received_sewing" for b in bundles):
        if assignment:
            return {"already_accepted": True, "received_count": 0}
        # Already received by a manager: claim only through manager assignment.
        raise HTTPException(409, "Already received; ask a manager to assign this work")
    gate = verify_sewing_accessory_gate(db, po_id)
    ids = receive_many_at_sewing(db, bundles, current, gate)
    db.flush()
    received_total = int(db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == po_id, Bundle.production_batch_id == batch_id,
        Bundle.sewing_factory_code == "ECO", Bundle.status == "received_sewing",
    ).scalar())
    if assignment is None:
        assignment = SewingAssignment(work_order_id=wo.id, production_batch_id=batch_id,
                                      sewing_flow_id=flow.id, quantity=received_total, created_by=current.id)
        db.add(assignment)
    else:
        assignment.quantity = max(assignment.quantity, received_total)
    if not wo.sewing_flow_id:
        wo.sewing_flow_id = flow.id
    db.flush()
    log_action(db, current, "band_receive", "SewingAssignment", assignment.id,
               new_value={"sewing_flow_id": flow.id, "bundle_ids": ids, "quantity": assignment.quantity})
    db.commit()
    return {"received_count": len(ids), "already_accepted": False}


def own_assignment(db, current, aid):
    flow = own_band(db, current)
    assignment = db.get(SewingAssignment, aid)
    if not assignment or assignment.sewing_flow_id != flow.id:
        raise HTTPException(404, "Assignment not found for this band")
    if assignment.status not in ("planned", "in_progress", "completed"):
        raise HTTPException(409, "Assignment was returned or cancelled")
    return assignment


@router.post("/{aid}/output")
def record_output(aid: int, payload: SewingRecordIn, db: DbSession, current: CurrentUser,
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    from app.api.routes.production import post_sewing
    assignment = own_assignment(db, current, aid)
    if (payload.input_qty != 0 or payload.rework_qty != 0 or payload.rejected_qty != 0
            or payload.operator_id not in (None, current.id)
            or payload.sewn_qty != payload.passed_qty + payload.failed_qty
            or payload.sewn_qty <= 0):
        raise HTTPException(400, "Enter positive final accepted/defective quantities; receipt input is recorded separately")
    if payload.failed_qty and not (payload.defect_reason or "").strip():
        raise HTTPException(400, "A defect reason is required")
    if payload.work_order_id != assignment.work_order_id or payload.sewing_assignment_id != assignment.id:
        raise HTTPException(403, "Output must belong to the selected assignment")
    if payload.production_batch_id != assignment.production_batch_id:
        raise HTTPException(403, "Output must belong to the selected batch")
    replay = replay_idempotent_response(db, scope="sewing:output", key=idempotency_key, payload=payload.model_dump())
    if replay is not None:
        return replay
    # Lock in the same order as the existing final-output handler.
    db.query(WorkOrder).filter(WorkOrder.id == assignment.work_order_id).with_for_update().one()
    db.refresh(assignment)
    if assignment.sewing_flow_id != current.sewing_band_id or assignment.status not in ("planned", "in_progress", "completed"):
        raise HTTPException(409, "This assignment changed; refresh before recording output")
    if payload.passed_qty + payload.failed_qty + payload.rejected_qty > max(0, assignment.quantity - assignment.completed_qty):
        raise HTTPException(400, "Output exceeds the remaining assignment quantity")
    wo = db.get(WorkOrder, assignment.work_order_id)
    received = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == wo.production_order_id, Bundle.status == "received_sewing", Bundle.sewing_factory_code == "ECO",
    )
    recorded = db.query(func.coalesce(func.sum(SewingRecord.passed_qty + SewingRecord.failed_qty + SewingRecord.rejected_qty), 0)).filter(
        SewingRecord.work_order_id == wo.id,
    )
    if assignment.production_batch_id is not None:
        received = received.filter(Bundle.production_batch_id == assignment.production_batch_id)
        recorded = recorded.filter(SewingRecord.production_batch_id == assignment.production_batch_id)
    if int(recorded.scalar()) + payload.sewn_qty > int(received.scalar()):
        raise HTTPException(409, "Final output exceeds bundles received for this work")
    return post_sewing(payload, db, current, idempotency_key)


class FinishIn(BaseModel):
    reason: str = Field(min_length=1, max_length=255)
    finished: bool = True


@router.post("/{aid}/finish")
def finish_line(aid: int, payload: FinishIn, db: DbSession,
                current: User = Depends(require_permissions("sewing.flows", "planning.production"))):
    if current.sewing_band_id:
        raise HTTPException(403, "Only a manager can finish short work or reopen a band")
    sewing_line_factory_scope(current, "ECO")
    assignment = db.get(SewingAssignment, aid)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    db.query(WorkOrder).filter(WorkOrder.id == assignment.work_order_id).with_for_update().one()
    db.refresh(assignment, with_for_update=True)
    flow = db.get(SewingFlow, assignment.sewing_flow_id)
    require_sewing_flow_access(current, flow)
    if not payload.reason.strip():
        raise HTTPException(422, "A reason is required")
    if assignment.status not in ("planned", "in_progress"):
        raise HTTPException(409, "This assignment is no longer active")
    assignment.line_finished_at = datetime.now(timezone.utc) if payload.finished else None
    assignment.line_finish_reason = payload.reason.strip() if payload.finished else None
    log_action(db, current, "finish_line" if payload.finished else "reopen_line", "SewingAssignment", aid,
               new_value={"reason": payload.reason, "finished": payload.finished})
    db.commit()
    return {"ok": True}
