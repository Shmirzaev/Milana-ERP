"""Correct unused sewing output, preserving cumulative and assignment accounting."""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import load_only
from app.core.deps import DbSession, require_permissions
from app.models import (User, WorkOrder, SewingRecord, SewingAssignment, SewingFlow,
                        SewingReplacementRequest, PackagingReceipt, PackagingRecord, CuttingRecord, PrintingRecord)
from app.services.factory_scope import require_work_order_factory_access
from app.services.audit import log_action
from app.services.workflow import advance_workflow
from app.services.sewing_assignment_policy import validate_assignment_progress

router = APIRouter(tags=["sewing_corrections"])


class CorrectionSizeQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, le=2_147_483_647, strict=True)


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    input_qty: int = Field(ge=0)
    sewn_qty: int = Field(ge=0)
    passed_qty: int = Field(ge=0)
    size_quantities: list[CorrectionSizeQuantity] = Field(default_factory=list, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


class DeleteInput(BaseModel):
    expected_version: int = Field(ge=0)


class SewingRecordHistoryOut(BaseModel):
    id: int
    work_order_id: int
    production_batch_id: int | None = None
    input_qty: int
    sewn_qty: int
    passed_qty: int
    failed_qty: int
    rejected_qty: int
    rework_qty: int
    line_name: str | None = None
    notes: str | None = None
    size_quantities: list[dict] | None = None
    created_at: datetime
    correction_version: int
    sewing_assignment_id: int | None = None
    assignment_applied_qty: int | None = None
    locked_reason: str | None = None


class SewingRecordHistoryPageOut(BaseModel):
    rows: list[SewingRecordHistoryOut]
    total: int
    page: int
    page_size: int
    has_more: bool


def snapshot(row):
    result = {key: getattr(row, key) for key in ("id", "work_order_id", "production_batch_id", "input_qty",
            "sewn_qty", "passed_qty", "failed_qty", "rejected_qty", "rework_qty", "line_name", "notes",
            "size_quantities", "created_at", "correction_version", "sewing_assignment_id", "assignment_applied_qty")}
    if result["created_at"].tzinfo is None:
        result["created_at"] = result["created_at"].replace(tzinfo=timezone.utc)
    return result


def reason(db, wo, record):
    if wo.status in ("cancelled", "rejected"):
        return "sewingEdit.closed"
    if record.failed_qty or record.rejected_qty or record.rework_qty or db.query(SewingReplacementRequest.id).filter(
        SewingReplacementRequest.sewing_work_order_id == wo.id,
        SewingReplacementRequest.production_batch_id == record.production_batch_id).first():
        return "sewingEdit.linkedReplacement"
    if db.query(PackagingReceipt.id).filter_by(source_work_order_id=wo.id,
            production_batch_id=record.production_batch_id).first():
        return "sewingEdit.handedOff"
    if db.query(PackagingRecord.id).join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id).filter(
            WorkOrder.production_order_id == wo.production_order_id,
            PackagingRecord.production_batch_id == record.production_batch_id).first():
        return "sewingEdit.handedOff"
    return None


def _batch_match_filter(column, batch_ids):
    conditions = []
    non_null_ids = [batch_id for batch_id in batch_ids if batch_id is not None]
    if non_null_ids:
        conditions.append(column.in_(non_null_ids))
    if None in batch_ids:
        conditions.append(column.is_(None))
    return or_(*conditions)


def _reasons_for_records(db, wo, records):
    if wo.status in ("cancelled", "rejected"):
        return {record.id: "sewingEdit.closed" for record in records}

    reasons = {
        record.id: "sewingEdit.linkedReplacement"
        for record in records
        if record.failed_qty or record.rejected_qty or record.rework_qty
    }
    candidates = [record for record in records if record.id not in reasons]
    if not candidates:
        return reasons

    batch_ids = {record.production_batch_id for record in candidates}
    replacement_batches = {
        batch_id
        for (batch_id,) in db.query(SewingReplacementRequest.production_batch_id)
        .filter(
            SewingReplacementRequest.sewing_work_order_id == wo.id,
            _batch_match_filter(SewingReplacementRequest.production_batch_id, batch_ids),
        )
        .distinct()
        .all()
    }
    receipt_batches = {
        batch_id
        for (batch_id,) in db.query(PackagingReceipt.production_batch_id)
        .filter(
            PackagingReceipt.source_work_order_id == wo.id,
            _batch_match_filter(PackagingReceipt.production_batch_id, batch_ids),
        )
        .distinct()
        .all()
    }
    packaging_batches = {
        batch_id
        for (batch_id,) in db.query(PackagingRecord.production_batch_id)
        .join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id)
        .filter(
            WorkOrder.production_order_id == wo.production_order_id,
            _batch_match_filter(PackagingRecord.production_batch_id, batch_ids),
        )
        .distinct()
        .all()
    }
    for record in candidates:
        batch_id = record.production_batch_id
        if batch_id in replacement_batches:
            reasons[record.id] = "sewingEdit.linkedReplacement"
        elif batch_id in receipt_batches or batch_id in packaging_batches:
            reasons[record.id] = "sewingEdit.handedOff"
    return reasons


def assignment_for(db, wo, row):
    if row.sewing_assignment_id:
        assignment = db.query(SewingAssignment).filter_by(id=row.sewing_assignment_id).with_for_update().first()
        applied = row.assignment_applied_qty
    elif row.assignment_applied_qty == 0:
        return None, 0
    else:
        # Legacy rows have no exact assignment foreign key. Infer only an unambiguous
        # line/batch and refuse historical saturation, moves or cancelled assignments.
        matches = db.query(SewingAssignment).join(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id).filter(
            SewingAssignment.work_order_id == wo.id, SewingAssignment.production_batch_id == row.production_batch_id,
            or_(func.lower(SewingFlow.name) == (row.line_name or "").lower(),
                func.lower(SewingFlow.code) == (row.line_name or "").lower())).all()
        if not matches:
            if db.query(SewingAssignment.id).filter_by(work_order_id=wo.id, production_batch_id=row.production_batch_id).first():
                raise HTTPException(409, "sewingEdit.assignmentAmbiguous")
            return None, 0
        if len(matches) != 1:
            raise HTTPException(409, "sewingEdit.assignmentAmbiguous")
        assignment = matches[0]
        line = db.get(SewingFlow, assignment.sewing_flow_id)
        total = db.query(func.coalesce(func.sum(SewingRecord.passed_qty + SewingRecord.failed_qty + SewingRecord.rejected_qty), 0)).filter(
            SewingRecord.work_order_id == wo.id, SewingRecord.production_batch_id == row.production_batch_id,
            func.lower(SewingRecord.line_name).in_([line.name.lower(), line.code.lower()])).scalar()
        if total != assignment.completed_qty:
            raise HTTPException(409, "sewingEdit.assignmentAmbiguous")
        applied = row.passed_qty
    if not assignment or assignment.status not in ("planned", "in_progress", "completed") or applied is None:
        raise HTTPException(409, "sewingEdit.assignmentAmbiguous")
    validate_assignment_progress(int(assignment.quantity or 0), int(assignment.completed_qty or 0))
    return assignment, applied


@router.get(
    "/work-orders/{wid}/sewing-records",
    response_model=list[SewingRecordHistoryOut] | SewingRecordHistoryPageOut,
)
def list_records(
    wid: int,
    db: DbSession,
    user: User = Depends(require_permissions("sewing.records")),
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    wo = db.get(WorkOrder, wid)
    if not wo or wo.operation != "sewing":
        raise HTTPException(404, "Not found")
    require_work_order_factory_access(user, db, wo)
    query = db.query(SewingRecord).options(load_only(
        SewingRecord.id,
        SewingRecord.work_order_id,
        SewingRecord.production_batch_id,
        SewingRecord.input_qty,
        SewingRecord.sewn_qty,
        SewingRecord.passed_qty,
        SewingRecord.failed_qty,
        SewingRecord.rejected_qty,
        SewingRecord.rework_qty,
        SewingRecord.line_name,
        SewingRecord.notes,
        SewingRecord.size_quantities,
        SewingRecord.created_at,
        SewingRecord.correction_version,
        SewingRecord.sewing_assignment_id,
        SewingRecord.assignment_applied_qty,
    )).filter_by(work_order_id=wid)
    ordered_query = query.order_by(SewingRecord.id.desc())
    if page is None and page_size is None:
        rows = ordered_query.all()
        reasons = _reasons_for_records(db, wo, rows)
        return [{**snapshot(row), "locked_reason": reasons.get(row.id)} for row in rows]

    page = page or 1
    page_size = page_size or 50
    total = query.count()
    rows = ordered_query.offset((page - 1) * page_size).limit(page_size).all()
    reasons = _reasons_for_records(db, wo, rows)
    return {
        "rows": [{**snapshot(row), "locked_reason": reasons.get(row.id)} for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


def locked_record(db, rid, user, version):
    identity = db.query(SewingRecord.work_order_id).filter_by(id=rid).first()
    if not identity:
        raise HTTPException(404, "Not found")
    wo = db.query(WorkOrder).filter_by(id=identity[0]).with_for_update().populate_existing().one()
    require_work_order_factory_access(user, db, wo)
    row = db.query(SewingRecord).filter_by(id=rid).with_for_update().populate_existing().first()
    if not row:
        raise HTTPException(404, "Not found")
    if row.correction_version != version:
        raise HTTPException(409, "sewingEdit.stale")
    blocked = reason(db, wo, row)
    if blocked:
        raise HTTPException(409, blocked)
    return wo, row


def apply(db, wo, row, user, payload=None):
    from app.api.routes.production import _context_work_order, _validated_sewing_size_quantities
    from app.schemas.production import SewingRecordIn
    old = snapshot(row)
    assignment, applied = assignment_for(db, wo, row)
    new_input = payload.input_qty if payload else 0
    new_sewn = payload.sewn_qty if payload else 0
    new_passed = payload.passed_qty if payload else 0
    if new_passed > new_sewn:
        raise HTTPException(422, "sewingEdit.invalidQuantity")
    # Derive cumulative input/output for this exact batch; inputs can be received
    # on one day and sewn later, so validate ledger totals rather than one row.
    totals = db.query(func.coalesce(func.sum(SewingRecord.input_qty), 0),
                      func.coalesce(func.sum(SewingRecord.sewn_qty), 0)).filter(
        SewingRecord.work_order_id == wo.id, SewingRecord.production_batch_id == row.production_batch_id).one()
    after_input = totals[0] - row.input_qty + new_input
    after_sewn = totals[1] - row.sewn_qty + new_sewn
    if after_sewn > after_input:
        raise HTTPException(409, "sewingEdit.invalidQuantity")
    cut = _context_work_order(db, wo, "cutting")
    printing = _context_work_order(db, wo, "printing")
    if row.production_batch_id is not None:
        def passed(model, column, upstream):
            if not upstream:
                return 0
            return int(db.query(func.coalesce(func.sum(column), 0)).filter(
                model.work_order_id == upstream.id,
                model.production_batch_id == row.production_batch_id).scalar())
        printed = passed(PrintingRecord, PrintingRecord.passed_qty, printing)
        limit = printed if printed > 0 else passed(CuttingRecord, CuttingRecord.passed_pieces, cut)
        proposed_input = after_input
    else:
        limit = int((printing.passed_qty if printing and printing.passed_qty else cut.passed_qty if cut else 0) or 0)
        proposed_input = wo.actual_input_qty - row.input_qty + new_input
    if new_input > row.input_qty and proposed_input > limit:
        raise HTTPException(409, "sewingEdit.upstreamLimit")
    if assignment:
        next_completed = assignment.completed_qty - applied + new_passed
        if next_completed < 0 or next_completed > assignment.quantity:
            raise HTTPException(409, "sewingEdit.assignmentLimit")
        validate_assignment_progress(int(assignment.quantity or 0), int(next_completed))
        assignment.completed_qty = next_completed
        assignment.status = "completed" if next_completed == assignment.quantity else "in_progress" if next_completed else "planned"
        assignment.actual_end = datetime.now(timezone.utc) if assignment.status == "completed" else None
    wo.actual_input_qty += new_input - row.input_qty
    wo.actual_output_qty += new_passed - row.passed_qty
    wo.passed_qty += new_passed - row.passed_qty
    if min(wo.actual_input_qty, wo.actual_output_qty, wo.passed_qty) < 0:
        raise HTTPException(409, "sewingEdit.assignmentAmbiguous")
    row.input_qty = new_input
    row.sewn_qty = new_sewn
    row.passed_qty = 0
    row.size_quantities = []
    db.flush()
    if payload:
        data = SewingRecordIn(work_order_id=wo.id, production_batch_id=row.production_batch_id,
                input_qty=new_input, sewn_qty=new_sewn, passed_qty=new_passed,
                size_quantities=[item.model_dump() for item in payload.size_quantities])
        row.size_quantities = _validated_sewing_size_quantities(db, wo, row.production_batch_id, data)
        row.passed_qty = new_passed
        row.notes = payload.notes
        row.correction_version += 1
        row.sewing_assignment_id = assignment.id if assignment else None
        row.assignment_applied_qty = new_passed if assignment else 0
    else:
        db.delete(row)
    if wo.status == "completed":
        wo.status = "in_progress"
        wo.end_time = None
    db.flush()
    advance_workflow(db, wo)
    log_action(db, user, "update" if payload else "delete", "SewingRecord", old["id"],
               old_value=old, new_value=snapshot(row) if payload else None)
    db.commit()
    return snapshot(row) if payload else {"deleted": True}


@router.patch("/sewing/records/{rid}")
def update(rid: int, payload: Correction, db: DbSession, user: User = Depends(require_permissions("sewing.records"))):
    wo, row = locked_record(db, rid, user, payload.expected_version)
    return apply(db, wo, row, user, payload)


@router.delete("/sewing/records/{rid}")
def delete(rid: int, payload: DeleteInput, db: DbSession, user: User = Depends(require_permissions("sewing.records"))):
    wo, row = locked_record(db, rid, user, payload.expected_version)
    return apply(db, wo, row, user)
