from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import WasteRecord, WasteSale, WasteDisposalRequest, User, StockBatch, Item
from app.schemas.waste import (
    WasteIn, WasteOut, WasteSaleIn, WasteSaleOut, WasteDisposalIn, WasteDisposalOut,
)
from app.services.audit import log_action

router = APIRouter(prefix="/waste", tags=["waste"])


def _unit_cost_for_waste(db: DbSession, item_id: int | None, batch_id: int | None) -> float:
    if batch_id:
        batch = db.get(StockBatch, batch_id)
        if batch:
            return float(batch.cost_per_unit or 0)
    if item_id:
        latest = (
            db.query(StockBatch)
            .filter(StockBatch.item_id == item_id)
            .order_by(StockBatch.id.desc())
            .first()
        )
        if latest:
            return float(latest.cost_per_unit or 0)
        item = db.get(Item, item_id)
        if item:
            return float(item.default_cost or 0)
    return 0.0


def _recalculate_value(db: DbSession, w: WasteRecord) -> float:
    unit_cost = _unit_cost_for_waste(db, w.item_id, w.batch_id)
    value = round(float(w.quantity or 0) * unit_cost, 2)
    if float(w.estimated_value or 0) != value:
        w.estimated_value = value
    return value


@router.get("", response_model=list[WasteOut])
def list_waste(db: DbSession, _: CurrentUser, status: str | None = None, sellable: bool | None = None):
    qry = db.query(WasteRecord)
    if status: qry = qry.filter(WasteRecord.status == status)
    if sellable is not None: qry = qry.filter(WasteRecord.sellable.is_(sellable))
    rows = qry.order_by(WasteRecord.id.desc()).all()
    changed = False
    for row in rows:
        before = float(row.estimated_value or 0)
        _recalculate_value(db, row)
        changed = changed or before != float(row.estimated_value or 0)
    if changed:
        db.commit()
    return rows


@router.post("", response_model=WasteOut, status_code=201)
def create_waste(payload: WasteIn, db: DbSession, current: CurrentUser):
    data = payload.model_dump()
    data["estimated_value"] = round(float(data.get("quantity") or 0) * _unit_cost_for_waste(db, data.get("item_id"), data.get("batch_id")), 2)
    w = WasteRecord(**data, created_by=current.id, status="recorded")
    db.add(w); db.flush()
    log_action(db, current, "create", "WasteRecord", w.id, new_value={"type": w.waste_type, "qty": float(w.quantity)})
    db.commit(); db.refresh(w)
    return w


@router.post("/{wid}/receive", response_model=WasteOut)
def receive_waste(wid: int, db: DbSession, current: User = Depends(require_permissions("waste.receive", "*"))):
    w = db.get(WasteRecord, wid)
    if not w: raise HTTPException(404, "Waste record not found")
    if w.status != "recorded":
        raise HTTPException(400, f"Can't receive from status '{w.status}'")
    w.status = "received_by_waste_department"
    log_action(db, current, "receive", "WasteRecord", w.id)
    db.commit(); db.refresh(w)
    return w


@router.post("/{wid}/sell", response_model=WasteSaleOut)
def sell_waste(wid: int, payload: WasteSaleIn, db: DbSession, current: User = Depends(require_permissions("waste.sell", "*"))):
    w = db.get(WasteRecord, wid)
    if not w: raise HTTPException(404, "Waste record not found")
    if not w.sellable: raise HTTPException(400, "Waste is not marked sellable")
    if w.status not in ("received_by_waste_department",):
        raise HTTPException(400, f"Cannot sell from status '{w.status}'")
    sale = WasteSale(
        waste_record_id=w.id,
        buyer_name=payload.buyer_name,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        total_amount=float(payload.quantity) * float(payload.unit_price),
        sold_by=current.id,
        sold_at=datetime.now(timezone.utc),
    )
    db.add(sale); db.flush()
    w.status = "sold"
    log_action(db, current, "sell", "WasteRecord", w.id, new_value={"amount": float(sale.total_amount)})
    db.commit(); db.refresh(sale)
    return sale


@router.post("/{wid}/request-disposal", response_model=WasteDisposalOut)
def request_disposal(wid: int, payload: WasteDisposalIn, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    w = db.get(WasteRecord, wid)
    if not w: raise HTTPException(404, "Waste record not found")
    if w.sellable: raise HTTPException(400, "Cannot dispose sellable waste; sell it instead")
    r = WasteDisposalRequest(waste_record_id=w.id, reason=payload.reason, requested_by=current.id, status="pending")
    db.add(r)
    w.status = "pending_disposal_approval"
    db.flush()
    log_action(db, current, "request_disposal", "WasteRecord", w.id)
    db.commit(); db.refresh(r)
    return r


@router.post("/disposal/{rid}/approve", response_model=WasteDisposalOut)
def approve_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    r = db.get(WasteDisposalRequest, rid)
    if not r: raise HTTPException(404, "Request not found")
    r.status = "approved"
    r.approved_by = current.id
    r.approved_at = datetime.now(timezone.utc)
    w = db.get(WasteRecord, r.waste_record_id)
    if w: w.status = "disposal_approved"
    log_action(db, current, "approve_disposal", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r


@router.post("/disposal/{rid}/reject", response_model=WasteDisposalOut)
def reject_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    r = db.get(WasteDisposalRequest, rid)
    if not r: raise HTTPException(404, "Request not found")
    r.status = "rejected"
    r.approved_by = current.id
    r.approved_at = datetime.now(timezone.utc)
    w = db.get(WasteRecord, r.waste_record_id)
    if w: w.status = "received_by_waste_department"
    log_action(db, current, "reject_disposal", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r


@router.post("/disposal/{rid}/mark-disposed", response_model=WasteDisposalOut)
def mark_disposed(rid: int, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    r = db.get(WasteDisposalRequest, rid)
    if not r: raise HTTPException(404, "Request not found")
    if r.status != "approved": raise HTTPException(400, "Disposal not approved yet")
    r.status = "disposed"
    w = db.get(WasteRecord, r.waste_record_id)
    if w: w.status = "disposed"
    log_action(db, current, "mark_disposed", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r
