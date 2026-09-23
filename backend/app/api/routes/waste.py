from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Header, Query
from sqlalchemy import func
from sqlalchemy.orm import load_only

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import WasteRecord, WasteSale, WasteDisposalRequest, User, StockBatch, Item
from app.schemas.waste import (
    WasteIn, WasteOut, WastePageOut, WasteSaleIn, WasteSaleOut, WasteDisposalIn, WasteDisposalOut,
)
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response

router = APIRouter(prefix="/waste", tags=["waste"])

MAX_WASTE_QUANTITY = Decimal("9999999999.9999")
MAX_WASTE_ESTIMATED_VALUE = Decimal("9999999999.99")
WASTE_QUANTITY_QUANTUM = Decimal("0.0001")


def _unit_cost_for_waste(db: DbSession, item_id: int | None, batch_id: int | None) -> Decimal:
    if batch_id:
        batch = db.get(StockBatch, batch_id)
        if batch:
            return Decimal(str(batch.cost_per_unit or 0))
    if item_id:
        latest = (
            db.query(StockBatch)
            .filter(StockBatch.item_id == item_id)
            .order_by(StockBatch.id.desc())
            .first()
        )
        if latest:
            return Decimal(str(latest.cost_per_unit or 0))
        item = db.get(Item, item_id)
        if item:
            return Decimal(str(item.default_cost or 0))
    return Decimal("0")


def _estimated_value_for_waste(db: DbSession, w: WasteRecord) -> float:
    unit_cost = _unit_cost_for_waste(db, w.item_id, w.batch_id)
    return float(round(Decimal(str(w.quantity or 0)) * unit_cost, 2))


def _validated_waste_values(quantity_value, unit_cost: Decimal) -> tuple[Decimal, Decimal]:
    try:
        quantity = Decimal(str(quantity_value))
        stored_quantity = quantity.quantize(WASTE_QUANTITY_QUANTUM)
        estimated_value = round(quantity * unit_cost, 2)
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "Waste quantity exceeds supported precision") from None
    if not quantity.is_finite() or quantity <= 0:
        raise HTTPException(422, "Waste quantity must be finite and greater than zero")
    if stored_quantity > MAX_WASTE_QUANTITY:
        raise HTTPException(422, f"Waste quantity must be no more than {MAX_WASTE_QUANTITY}")
    if not estimated_value.is_finite() or estimated_value > MAX_WASTE_ESTIMATED_VALUE:
        raise HTTPException(422, "Waste estimated value exceeds supported precision")
    return quantity, estimated_value


@router.get("", response_model=list[WasteOut] | WastePageOut)
def list_waste(
    db: DbSession,
    _: CurrentUser,
    status: str | None = None,
    sellable: bool | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    qry = db.query(WasteRecord).options(load_only(
        WasteRecord.id,
        WasteRecord.production_order_id,
        WasteRecord.work_order_id,
        WasteRecord.source_department_id,
        WasteRecord.item_id,
        WasteRecord.batch_id,
        WasteRecord.waste_type,
        WasteRecord.quantity,
        WasteRecord.unit,
        WasteRecord.reason,
        WasteRecord.sellable,
        WasteRecord.estimated_value,
        WasteRecord.status,
        WasteRecord.created_at,
    ))
    if status: qry = qry.filter(WasteRecord.status == status)
    if sellable is not None: qry = qry.filter(WasteRecord.sellable.is_(sellable))
    total = None
    if page is not None or page_size is not None:
        page = page or 1
        page_size = page_size or 100
        total = qry.order_by(None).count()
    qry = qry.order_by(WasteRecord.id.desc())
    if total is not None:
        qry = qry.offset((page - 1) * page_size).limit(page_size)
    rows = qry.all()
    row_ids = [int(row.id) for row in rows]
    sold_by_waste_id = dict(
        db.query(WasteSale.waste_record_id, func.coalesce(func.sum(WasteSale.quantity), 0))
        .filter(WasteSale.waste_record_id.in_(row_ids))
        .group_by(WasteSale.waste_record_id)
        .all()
    ) if row_ids else {}
    # Preserve the existing live-estimate response without rewriting the
    # valuation snapshot stored with the historical waste record.
    payloads = [
        WasteOut.model_validate(row).model_copy(
            update={
                "estimated_value": _estimated_value_for_waste(db, row),
                "remaining_quantity": float(max(
                    Decimal("0"),
                    Decimal(str(row.quantity or 0)) - Decimal(sold_by_waste_id.get(row.id, 0) or 0),
                )),
            },
        )
        for row in rows
    ]
    if total is None:
        return payloads
    return {
        "rows": payloads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.post("", response_model=WasteOut, status_code=201)
def create_waste(payload: WasteIn, db: DbSession, current: User = Depends(require_permissions(
    "cutting.records", "printing.records", "sewing.records", "packaging.records",
    "waste.receive", "planning.production", "management.approve", "*",
))):
    data = payload.model_dump()
    unit_cost = _unit_cost_for_waste(db, data.get("item_id"), data.get("batch_id"))
    data["quantity"], data["estimated_value"] = _validated_waste_values(data.get("quantity"), unit_cost)
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
def sell_waste(
    wid: int,
    payload: WasteSaleIn,
    db: DbSession,
    current: User = Depends(require_permissions("waste.sell", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    idempotency_scope = f"waste.sales.{current.id}.{wid}"
    fingerprint_payload = {"waste_record_id": wid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(
        db, user=current, scope=idempotency_scope, key=idempotency_key, payload=fingerprint_payload,
    )
    if replay:
        return replay

    w = (
        db.query(WasteRecord)
        .filter(WasteRecord.id == wid)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if not w: raise HTTPException(404, "Waste record not found")

    # A concurrent request can store its replay only after releasing this
    # parent lock, so check the key again after the serialized handoff.
    replay = replay_idempotent_response(
        db, user=current, scope=idempotency_scope, key=idempotency_key, payload=fingerprint_payload,
    )
    if replay:
        return replay

    if not w.sellable: raise HTTPException(400, "Waste is not marked sellable")
    if w.status not in ("received_by_waste_department",):
        raise HTTPException(400, f"Cannot sell from status '{w.status}'")

    buyer_name, quantity, unit_price, total_amount = _validated_sale_values(payload)
    remaining_quantity = _remaining_sale_quantity(db, w)
    if quantity > remaining_quantity:
        raise HTTPException(400, f"Sale quantity exceeds remaining waste quantity {remaining_quantity:f}")

    sale = WasteSale(
        waste_record_id=w.id,
        buyer_name=buyer_name,
        quantity=quantity,
        unit_price=unit_price,
        total_amount=total_amount,
        sold_by=current.id,
        sold_at=datetime.now(timezone.utc),
    )
    db.add(sale); db.flush()
    remaining_after_sale = remaining_quantity - quantity
    if remaining_after_sale == 0:
        w.status = "sold"
    log_action(db, current, "sell", "WasteRecord", w.id, new_value={
        "quantity": float(quantity),
        "remaining_quantity": float(remaining_after_sale),
        "amount": float(total_amount),
    })
    response = WasteSaleOut.model_validate(sale).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope=idempotency_scope,
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
    )
    db.commit(); db.refresh(sale)
    return response


def _validated_sale_values(payload: WasteSaleIn) -> tuple[str, Decimal, Decimal, Decimal]:
    buyer_name = payload.buyer_name.strip()
    if not buyer_name:
        raise HTTPException(400, "Buyer name is required")
    if len(buyer_name) > 255:
        raise HTTPException(400, "Buyer name must be at most 255 characters")
    try:
        quantity = Decimal(str(payload.quantity))
        unit_price = Decimal(str(payload.unit_price))
        if not quantity.is_finite() or quantity <= 0:
            raise HTTPException(400, "Sale quantity must be finite and greater than zero")
        if not unit_price.is_finite() or unit_price < 0:
            raise HTTPException(400, "Unit price must be finite and nonnegative")
        if quantity != quantity.quantize(Decimal("0.0001")):
            raise HTTPException(400, "Sale quantity supports at most 4 decimal places")
        if unit_price != unit_price.quantize(Decimal("0.01")):
            raise HTTPException(400, "Unit price supports at most 2 decimal places")
        # Match PostgreSQL NUMERIC(14,2) storage for positive sale totals.
        total_amount = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise HTTPException(400, "Sale values exceed supported precision") from None
    if quantity > Decimal("9999999999.9999") or unit_price > Decimal("9999999999.99"):
        raise HTTPException(400, "Sale values exceed supported precision")
    if total_amount > Decimal("999999999999.99"):
        raise HTTPException(400, "Sale total exceeds supported precision")
    return buyer_name, quantity, unit_price, total_amount


def _remaining_sale_quantity(db: DbSession, waste_record: WasteRecord) -> Decimal:
    original_quantity = Decimal(str(waste_record.quantity or 0))
    if not original_quantity.is_finite() or original_quantity <= 0:
        raise HTTPException(400, "Stored waste quantity is invalid")
    sold_quantity = Decimal("0")
    for row in db.query(WasteSale.quantity).filter(WasteSale.waste_record_id == waste_record.id).all():
        historical_quantity = Decimal(str(row[0]))
        if not historical_quantity.is_finite() or historical_quantity <= 0:
            raise HTTPException(400, "Historical waste sale quantity is invalid")
        sold_quantity += historical_quantity
    remaining_quantity = original_quantity - sold_quantity
    if remaining_quantity <= 0:
        raise HTTPException(400, "Waste has no remaining sellable quantity")
    return remaining_quantity


@router.post("/{wid}/request-disposal", response_model=WasteDisposalOut)
def request_disposal(wid: int, payload: WasteDisposalIn, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    w = _disposal_waste_for_update(db, wid)
    _require_disposal_waste(w, "received_by_waste_department")
    r = WasteDisposalRequest(waste_record_id=w.id, reason=payload.reason, requested_by=current.id, status="pending")
    db.add(r)
    w.status = "pending_disposal_approval"
    db.flush()
    log_action(db, current, "request_disposal", "WasteRecord", w.id)
    db.commit(); db.refresh(r)
    return r


def _disposal_waste_for_update(db: DbSession, wid: int) -> WasteRecord:
    w = db.query(WasteRecord).filter(WasteRecord.id == wid).with_for_update().populate_existing().first()
    if not w:
        raise HTTPException(404, "Waste record not found")
    return w


def _require_disposal_state(w: WasteRecord, expected_status: str) -> None:
    if w.status != expected_status:
        raise HTTPException(400, f"Cannot dispose from status '{w.status}'")


def _require_disposal_waste(w: WasteRecord, expected_status: str) -> None:
    _require_disposal_state(w, expected_status)
    if w.sellable:
        raise HTTPException(400, "Cannot dispose sellable waste; sell it instead")
    if not isfinite(float(w.quantity)) or w.quantity <= 0:
        raise HTTPException(400, "Waste quantity must be finite and greater than zero")


def _disposal_request_for_update(db: DbSession, rid: int) -> tuple[WasteDisposalRequest, WasteRecord]:
    wid = db.query(WasteDisposalRequest.waste_record_id).filter(WasteDisposalRequest.id == rid).scalar()
    if wid is None:
        raise HTTPException(404, "Request not found")
    # All disposal mutations lock the parent first, including new requests.
    w = _disposal_waste_for_update(db, wid)
    r = db.query(WasteDisposalRequest).filter(WasteDisposalRequest.id == rid).with_for_update().populate_existing().first()
    if not r:
        raise HTTPException(404, "Request not found")
    return r, w


@router.post("/disposal/{rid}/approve", response_model=WasteDisposalOut)
def approve_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    r, w = _disposal_request_for_update(db, rid)
    if r.status != "pending":
        raise HTTPException(400, "Disposal request is not pending")
    _require_disposal_waste(w, "pending_disposal_approval")
    r.status = "approved"
    r.approved_by = current.id
    r.approved_at = datetime.now(timezone.utc)
    w.status = "disposal_approved"
    log_action(db, current, "approve_disposal", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r


@router.post("/disposal/{rid}/reject", response_model=WasteDisposalOut)
def reject_disposal(rid: int, db: DbSession, current: User = Depends(require_permissions("management.approve", "*"))):
    r, w = _disposal_request_for_update(db, rid)
    if r.status != "pending":
        raise HTTPException(400, "Disposal request is not pending")
    # Rejection safely withdraws even a historically invalid disposal request.
    _require_disposal_state(w, "pending_disposal_approval")
    r.status = "rejected"
    r.approved_by = current.id
    r.approved_at = datetime.now(timezone.utc)
    w.status = "received_by_waste_department"
    log_action(db, current, "reject_disposal", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r


@router.post("/disposal/{rid}/mark-disposed", response_model=WasteDisposalOut)
def mark_disposed(rid: int, db: DbSession, current: User = Depends(require_permissions("waste.disposal", "*"))):
    r, w = _disposal_request_for_update(db, rid)
    if r.status != "approved": raise HTTPException(400, "Disposal not approved yet")
    _require_disposal_waste(w, "disposal_approved")
    r.status = "disposed"
    w.status = "disposed"
    log_action(db, current, "mark_disposed", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r
