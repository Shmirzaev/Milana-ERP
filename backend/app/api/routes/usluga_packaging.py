"""Customer-owned goods are confirmed by size without issuing warehouse packs."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.core.deps import DbSession, require_permissions
from app.models import ProductionOrder, ProductionOrderItem, SewingRecord, User, WorkOrder
from app.services.audit import log_action
from app.services.packaging_scope import require_packaging_work_order_access
from app.services.workflow import sync_production_order_status

router = APIRouter(prefix="/work-orders", tags=["production"])


class SizeConfirmation(BaseModel):
    size: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=0, le=10000000, strict=True)


class Confirmation(BaseModel):
    version: int = Field(ge=0)
    items: list[SizeConfirmation] = Field(min_length=1, max_length=200)
    done: bool = False


def _work(db, current, wid):
    wo = db.get(WorkOrder, wid)
    if not wo or wo.operation != "packaging":
        raise HTTPException(404, "Packaging work order not found")
    require_packaging_work_order_access(current, db, wo)
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po or po.source_type != "usluga":
        raise HTTPException(400, "Size confirmation is only available for Usluga packaging")
    return wo, po


@router.get("/{wid}/usluga-packaging")
def read_confirmation(wid: int, db: DbSession,
                      current: User = Depends(require_permissions("packaging.records", "usluga.view", "*"))):
    wo, po = _work(db, current, wid)
    stored = wo.service_packaging_json or {}
    sizes = sorted({row.size for row in db.query(ProductionOrderItem).filter_by(production_order_id=po.id)}, key=str)
    return {"version": stored.get("version", 0), "done": stored.get("done", False),
            "items": stored.get("items") or [{"size": size, "quantity": 0} for size in sizes],
            "handed_over": po.handed_over_at is not None}


@router.put("/{wid}/usluga-packaging")
def save_confirmation(wid: int, payload: Confirmation, db: DbSession,
                      current: User = Depends(require_permissions("packaging.records", "*"))):
    wo, po = _work(db, current, wid)
    po = db.query(ProductionOrder).filter_by(id=po.id).with_for_update().populate_existing().one()
    works = db.query(WorkOrder).filter_by(production_order_id=po.id).order_by(WorkOrder.id).with_for_update(of=WorkOrder).populate_existing().all()
    wo = next(row for row in works if row.id == wid)
    if wo.is_blocked:
        raise HTTPException(409, "Work order is blocked")
    sewing = next((row for row in works if row.operation == "sewing" and row.production_batch_id == wo.production_batch_id), None)
    if po.handed_over_at or wo.status in ("cancelled", "rejected"):
        raise HTTPException(409, "Handed-over or cancelled work cannot be edited")
    if not sewing or int(sewing.passed_qty or 0) <= 0:
        raise HTTPException(409, "Sewing must confirm output before packaging")
    old = wo.service_packaging_json or {}
    if payload.version != old.get("version", 0):
        raise HTTPException(409, "Packaging quantities changed; reload before saving")
    allowed = {row.size for row in db.query(ProductionOrderItem).filter_by(production_order_id=po.id)}
    items = [{"size": row.size.strip(), "quantity": row.quantity} for row in payload.items]
    if len({row["size"] for row in items}) != len(items) or any(row["size"] not in allowed for row in items):
        raise HTTPException(422, "Select distinct order sizes")
    total = sum(row["quantity"] for row in items)
    previous = int(old.get("confirmed_quantity", 0))
    legacy = max(0, int(wo.passed_qty or 0) - previous)
    available = max(0, int(sewing.passed_qty or 0) - legacy)
    if total > available:
        raise HTTPException(409, "Packaging quantity exceeds confirmed sewing output")
    if payload.done and (sewing.status != "completed" or total != available or total + legacy <= 0):
        raise HTTPException(409, "Confirm all sewn items and complete Sewing before marking packaging done")
    # When Sewing recorded every size, enforce its authoritative size totals.
    completed = {}
    records = db.query(SewingRecord).filter_by(work_order_id=sewing.id).all()
    for record in records:
        for row in record.size_quantities or []:
            completed[row["size"]] = completed.get(row["size"], 0) + int(row["quantity"])
    if not legacy and sum(completed.values()) == int(sewing.passed_qty or 0):
        if any(row["quantity"] > completed.get(row["size"], 0) for row in items):
            raise HTTPException(409, "A size quantity exceeds confirmed sewing output")
    confirmed = total if payload.done else 0
    wo.service_packaging_json = {"version": payload.version + 1, "items": items, "done": payload.done,
                                 "confirmed_quantity": confirmed}
    wo.actual_output_qty = int(wo.actual_output_qty or 0) - previous + confirmed
    wo.passed_qty = legacy + confirmed
    wo.actual_input_qty = max(int(wo.actual_input_qty or 0), wo.passed_qty)
    wo.status = "completed" if payload.done else "in_progress"
    wo.end_time = datetime.now(timezone.utc) if payload.done else None
    db.flush()
    sync_production_order_status(db, po.id)
    log_action(db, current, "confirm_service_packaging", "WorkOrder", wo.id,
               old_value=old, new_value=wo.service_packaging_json)
    db.commit()
    return read_confirmation(wid, db, current)
