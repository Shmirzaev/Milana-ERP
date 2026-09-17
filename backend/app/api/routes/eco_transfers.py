"""Milana-owned fabric sent offsite and returned; never receipts into Eco inventory."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import lazyload
from app.core.deps import DbSession, require_permissions
from app.models import EcoFabricDispatch, EcoFabricRoll, Item, StockBatch, StockMovement, User
from app.api.routes.fabric_scans import parse_roll, TASHKENT
from app.services.audit import log_action
from app.services.factory_scope import selected_factory_code
from app.services.inventory import reserved_stock_for_batch, available_stock_for_item
from app.services.inventory_access import MATERIAL_CATEGORIES

router = APIRouter(prefix="/eco-fabric-transfers", tags=["eco_fabric_transfers"])


def access(user: User = Depends(require_permissions("inventory.eco_transfers"))):
    if selected_factory_code(user) != "MIL":
        raise HTTPException(403, "ecoTransfers.milanaOnly")
    return user


class ScanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    codes: list[str] = Field(min_length=1, max_length=500)


class ReturnIn(ScanIn):
    request_key: UUID
    dispatch_id: int = Field(gt=0)


def batch_lock(db, batch_id):
    batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=batch_id).with_for_update().first()
    if not batch or not batch.item or batch.item.category not in MATERIAL_CATEGORIES:
        raise HTTPException(404, "fabricScans.fabric_not_found")
    return batch


def quantity(db, batch, roll):
    weights = batch.roll_weights_kg or []
    if batch.unit.lower() not in ("kg", "kilogram", "kilograms"):
        raise HTTPException(409, "ecoTransfers.needWeights")
    if roll > max(batch.piece_count or 0, len(weights)):
        raise HTTPException(400, "fabricScans.roll_not_found")
    if not weights:
        # Legacy equal-weight labels are safe only before any stock use/correction.
        used = db.query(StockMovement.id).filter(StockMovement.batch_id == batch.id,
                    StockMovement.movement_type != "receive").first()
        if used or not batch.piece_count or batch.quantity <= 0:
            raise HTTPException(409, "ecoTransfers.needWeights")
        cents = int(Decimal(batch.quantity) * 100)
        each, remainder = divmod(cents, batch.piece_count)
        weights = [(each + (1 if n < remainder else 0)) / 100 for n in range(batch.piece_count)]
    if roll > len(weights) or Decimal(str(weights[roll - 1])) <= 0:
        raise HTTPException(409, "ecoTransfers.needWeights")
    return Decimal(str(weights[roll - 1])), weights


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def roll_data(row):
    return {"id": row.id, "dispatch_id": row.dispatch_id, "code": f"B{row.batch_id}-R{row.roll_number}",
            "fabric_name": row.fabric_name, "batch_no": row.batch_no, "color": row.color,
            "roll_number": row.roll_number, "quantity": row.quantity, "unit": row.unit,
            "returned_at": utc(row.returned_at), "return_operator_name": row.return_operator_name}


def dispatch_data(db, dispatch):
    rows = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id).order_by(EcoFabricRoll.id).all()
    return {"id": dispatch.id, "number": f"ECO-{dispatch.id:06d}", "sent_at": utc(dispatch.sent_at),
            "operator_name": dispatch.operator_name, "rows": [roll_data(row) for row in rows],
            "sent_rolls": len(rows), "outstanding_rolls": sum(row.returned_at is None for row in rows),
            "sent_kg": sum(Decimal(row.quantity) for row in rows),
            "outstanding_kg": sum(Decimal(row.quantity) for row in rows if row.returned_at is None)}


@router.post("/scan")
def scan(payload: ScanIn, db: DbSession, user: User = Depends(access)):
    batch_id, roll = parse_roll(payload.code)
    batch = batch_lock(db, batch_id)
    outstanding = db.query(EcoFabricRoll).filter_by(batch_id=batch_id, roll_number=roll, returned_at=None).first()
    if outstanding:
        return {**roll_data(outstanding), "status": "sent"}
    amount, _ = quantity(db, batch, roll)
    if batch.archived_at or Decimal(batch.quantity) < amount:
        raise HTTPException(409, "ecoTransfers.unavailable")
    return {"code": f"B{batch_id}-R{roll}", "status": "available", "fabric_name": batch.item.name,
            "batch_no": batch.batch_no, "color": batch.color, "roll_number": roll, "quantity": amount, "unit": batch.unit}


@router.post("/send")
def send(payload: SendIn, db: DbSession, user: User = Depends(access)):
    identities = sorted(set(parse_roll(code) for code in payload.codes))
    if len(identities) != len(payload.codes):
        raise HTTPException(400, "ecoTransfers.duplicate")
    # Lock batches in stable order; all mutation paths share the inventory row locks.
    batches = {bid: batch_lock(db, bid) for bid in sorted({bid for bid, _ in identities})}
    key = str(payload.request_key)
    previous = db.query(EcoFabricDispatch).filter_by(request_key=key).first()
    if previous:
        old = db.query(EcoFabricRoll).filter_by(dispatch_id=previous.id).all()
        if sorted((r.batch_id, r.roll_number) for r in old) != identities:
            raise HTTPException(409, "ecoTransfers.changedRequest")
        return dispatch_data(db, previous)
    dispatch = EcoFabricDispatch(request_key=key, created_by=user.id, operator_name=user.name,
                                  sent_at=datetime.now(timezone.utc), remaining_inventory=[])
    db.add(dispatch)
    db.flush()
    for bid, roll in identities:
        batch = batches[bid]
        if db.query(EcoFabricRoll.id).filter_by(batch_id=bid, roll_number=roll, returned_at=None).first():
            raise HTTPException(409, "ecoTransfers.alreadySent")
        amount, weights = quantity(db, batch, roll)
        if batch.archived_at or batch.quantity - Decimal(str(reserved_stock_for_batch(db, bid))) < amount:
            raise HTTPException(409, "ecoTransfers.unavailable")
        if Decimal(str(available_stock_for_item(db, batch.item_id, batch.warehouse_id))) < amount:
            raise HTTPException(409, "ecoTransfers.unavailable")
        batch.roll_weights_kg = weights
        batch.quantity = Decimal(batch.quantity) - amount
        if batch.quantity == 0:
            batch.archived_at = dispatch.sent_at
            batch.archived_by = user.id
        row = EcoFabricRoll(dispatch_id=dispatch.id, batch_id=bid, roll_number=roll,
                           fabric_name=batch.item.name, batch_no=batch.batch_no, color=batch.color,
                           quantity=amount, unit=batch.unit)
        db.add(row)
        db.add(StockMovement(movement_type="issue", item_id=batch.item_id, batch_id=bid,
                from_warehouse_id=batch.warehouse_id, quantity=amount, unit=batch.unit,
                reference_type="EcoFabricDispatch", reference_id=dispatch.id, created_by=user.id))
        db.flush()
    # Immutable snapshot: later returns/consumption never rewrite this dispatch's PDF.
    offsite_counts = dict(db.query(EcoFabricRoll.batch_id, func.count(EcoFabricRoll.id)).filter(
        EcoFabricRoll.returned_at.is_(None)).group_by(EcoFabricRoll.batch_id).all())
    dispatch.remaining_inventory = [{"fabric_name": item.name, "batch_no": batch.batch_no,
                "color": batch.color, "quantity": str(batch.quantity), "unit": batch.unit,
                "rolls": max(0, batch.piece_count - offsite_counts.get(batch.id, 0)) if batch.piece_count is not None else None}
        for batch, item in db.query(StockBatch, Item).join(Item, Item.id == StockBatch.item_id).filter(
            Item.category.in_(MATERIAL_CATEGORIES), StockBatch.archived_at.is_(None), StockBatch.quantity > 0,
        ).order_by(Item.name, StockBatch.batch_no, StockBatch.id).all()]
    result = dispatch_data(db, dispatch)
    log_action(db, user, "send", "EcoFabricDispatch", dispatch.id, new_value=result)
    db.commit()
    return result


@router.post("/return")
def receive(payload: ReturnIn, db: DbSession, user: User = Depends(access)):
    bid, roll = parse_roll(payload.code)
    batch = batch_lock(db, bid)
    previous = db.query(EcoFabricRoll).filter_by(return_key=str(payload.request_key)).first()
    if previous:
        if (previous.batch_id, previous.roll_number, previous.dispatch_id) != (bid, roll, payload.dispatch_id):
            raise HTTPException(409, "ecoTransfers.changedRequest")
        return roll_data(previous)
    row = db.query(EcoFabricRoll).filter_by(batch_id=bid, roll_number=roll,
                    dispatch_id=payload.dispatch_id).with_for_update().first()
    if not row or row.returned_at is not None:
        raise HTTPException(409, "ecoTransfers.notSent")
    if batch.unit != row.unit or not batch.item.is_active:
        raise HTTPException(409, "ecoTransfers.batchChanged")
    before = roll_data(row)
    row.returned_at = datetime.now(timezone.utc)
    row.returned_by = user.id
    row.return_operator_name = user.name
    row.return_key = str(payload.request_key)
    batch.quantity = Decimal(batch.quantity) + Decimal(row.quantity)
    batch.archived_at = None
    batch.archived_by = None
    db.add(StockMovement(movement_type="return", item_id=batch.item_id, batch_id=bid,
            to_warehouse_id=batch.warehouse_id, quantity=row.quantity, unit=row.unit,
            reference_type="EcoFabricReturn", reference_id=row.id, created_by=user.id))
    log_action(db, user, "return", "EcoFabricRoll", row.id, old_value=before, new_value=roll_data(row))
    db.commit()
    return roll_data(row)


@router.get("")
def report(db: DbSession, user: User = Depends(access), report_date: date | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)):
    query = db.query(EcoFabricDispatch)
    if report_date:
        start = datetime.combine(report_date, time.min, TASHKENT).astimezone(timezone.utc)
        query = query.filter(EcoFabricDispatch.sent_at >= start, EcoFabricDispatch.sent_at < start + timedelta(days=1))
    outstanding = db.query(func.count(EcoFabricRoll.id), func.coalesce(func.sum(EcoFabricRoll.quantity), 0)).filter_by(returned_at=None).one()
    rows = query.order_by(EcoFabricDispatch.sent_at.desc(), EcoFabricDispatch.id.desc()).offset((page-1)*page_size).limit(page_size).all()
    return {"total": query.count(), "outstanding_rolls": outstanding[0], "outstanding_kg": outstanding[1],
            "items": [dispatch_data(db, row) for row in rows]}


@router.get("/{dispatch_id}/pdf")
def pdf(dispatch_id: int, db: DbSession, lang: str = "en", user: User = Depends(access)):
    from app.services.eco_transfer_pdf import build_pdf
    dispatch = db.get(EcoFabricDispatch, dispatch_id)
    if not dispatch:
        raise HTTPException(404, "Not found")
    data = dispatch_data(db, dispatch)
    return Response(build_pdf(data, lang=lang), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{data["number"]}.pdf"'})
