"""Waste lifecycle: recorded, received, sold or disposed.

Owns the transaction for every waste write. The router only binds the request,
the caller's permissions and the response envelope.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite

from fastapi import HTTPException

from app.libs.dto.inventory.waste_input import WasteIn
from app.libs.dto.inventory.waste_output import WasteOut
from app.libs.dto.inventory.waste_sale_input import WasteSaleIn
from app.libs.dto.inventory.waste_sale_output import WasteSaleOut
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.schemas import Item, StockBatch, User, WasteDisposalRequest, WasteRecord, WasteSale


def _unit_cost_for_waste(db, item_id: int | None, batch_id: int | None) -> float:
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


def _estimated_value_for_waste(db, w: WasteRecord) -> float:
    unit_cost = _unit_cost_for_waste(db, w.item_id, w.batch_id)
    return round(float(w.quantity or 0) * unit_cost, 2)


def list_waste(db, status: str | None = None, sellable: bool | None = None) -> list[WasteOut]:
    qry = db.query(WasteRecord)
    if status: qry = qry.filter(WasteRecord.status == status)
    if sellable is not None: qry = qry.filter(WasteRecord.sellable.is_(sellable))
    rows = qry.order_by(WasteRecord.id.desc()).all()
    # Preserve the existing live-estimate response without rewriting the
    # valuation snapshot stored with the historical waste record.
    return [
        WasteOut.model_validate(row).model_copy(
            update={"estimated_value": _estimated_value_for_waste(db, row)},
        )
        for row in rows
    ]


def create_waste(db, payload: WasteIn, current: User) -> WasteRecord:
    data = payload.model_dump()
    data["estimated_value"] = round(float(data.get("quantity") or 0) * _unit_cost_for_waste(db, data.get("item_id"), data.get("batch_id")), 2)
    w = WasteRecord(**data, created_by=current.id, status="recorded")
    db.add(w); db.flush()
    log_action(db, current, "create", "WasteRecord", w.id, new_value={"type": w.waste_type, "qty": float(w.quantity)})
    db.commit(); db.refresh(w)
    return w


def receive_waste(db, wid: int, current: User) -> WasteRecord:
    w = db.get(WasteRecord, wid)
    if not w: raise HTTPException(404, "Waste record not found")
    if w.status != "recorded":
        raise HTTPException(400, f"Can't receive from status '{w.status}'")
    w.status = "received_by_waste_department"
    log_action(db, current, "receive", "WasteRecord", w.id)
    db.commit(); db.refresh(w)
    return w


def _validated_sale_values(payload: WasteSaleIn) -> tuple[str, Decimal, Decimal, Decimal]:
    """Validate a sale against the real NUMERIC column widths.

    waste_sales stores quantity NUMERIC(14,4), unit_price NUMERIC(12,2) and
    total_amount NUMERIC(14,2), so precision is validated here rather than
    discovered as a database error at write time.
    """
    buyer_name = payload.buyer_name.strip()
    if not buyer_name:
        raise HTTPException(400, "Buyer name is required")
    if len(buyer_name) > 255:
        raise HTTPException(400, "Buyer name must be at most 255 characters")
    try:
        quantity = Decimal(str(payload.quantity))
        unit_price = Decimal(str(payload.unit_price))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(400, "Sale values exceed supported precision") from None
    if not quantity.is_finite() or quantity <= 0:
        raise HTTPException(400, "Sale quantity must be finite and greater than zero")
    if not unit_price.is_finite() or unit_price < 0:
        raise HTTPException(400, "Unit price must be finite and nonnegative")
    if quantity != quantity.quantize(Decimal("0.0001")):
        raise HTTPException(400, "Sale quantity supports at most 4 decimal places")
    if unit_price != unit_price.quantize(Decimal("0.01")):
        raise HTTPException(400, "Unit price supports at most 2 decimal places")
    total_amount = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantity > Decimal("9999999999.9999"):
        raise HTTPException(400, "Sale quantity exceeds supported precision")
    if unit_price > Decimal("9999999999.99"):
        raise HTTPException(400, "Unit price exceeds supported precision")
    if total_amount > Decimal("999999999999.99"):
        raise HTTPException(400, "Sale total exceeds supported precision")
    return buyer_name, quantity, unit_price, total_amount


def _remaining_sale_quantity(db, waste_record: WasteRecord) -> Decimal:
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


def sell_waste(db, wid: int, payload: WasteSaleIn, current: User, idempotency_key: str | None = None) -> dict:
    idempotency_scope = f"waste.sales.{current.id}.{wid}"
    fingerprint_payload = {"waste_record_id": wid, **payload.model_dump(mode="json")}
    replay = replay_idempotent_response(
        db, scope=idempotency_scope, key=idempotency_key, payload=fingerprint_payload,
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
    if not w:
        raise HTTPException(404, "Waste record not found")

    # A concurrent request can store its replay only after releasing this
    # parent lock, so check the key again after the serialized handoff.
    replay = replay_idempotent_response(
        db, scope=idempotency_scope, key=idempotency_key, payload=fingerprint_payload,
    )
    if replay:
        return replay

    if not w.sellable:
        raise HTTPException(400, "Waste is not marked sellable")
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
    db.add(sale)
    db.flush()
    remaining_after_sale = remaining_quantity - quantity
    # Only a sale that exhausts the record closes it. Marking it sold on a
    # partial sale stranded the leftover waste as unsellable.
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
    db.commit()
    return response


def _disposal_waste_for_update(db, wid: int) -> WasteRecord:
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


def _disposal_request_for_update(db, rid: int) -> tuple[WasteDisposalRequest, WasteRecord]:
    wid = db.query(WasteDisposalRequest.waste_record_id).filter(WasteDisposalRequest.id == rid).scalar()
    if wid is None:
        raise HTTPException(404, "Request not found")
    # All disposal mutations lock the parent first, including new requests.
    w = _disposal_waste_for_update(db, wid)
    r = db.query(WasteDisposalRequest).filter(WasteDisposalRequest.id == rid).with_for_update().populate_existing().first()
    if not r:
        raise HTTPException(404, "Request not found")
    return r, w


def request_disposal(db, wid: int, payload, current: User) -> WasteDisposalRequest:
    w = _disposal_waste_for_update(db, wid)
    _require_disposal_waste(w, "received_by_waste_department")
    r = WasteDisposalRequest(waste_record_id=w.id, reason=payload.reason, requested_by=current.id, status="pending")
    db.add(r)
    w.status = "pending_disposal_approval"
    db.flush()
    log_action(db, current, "request_disposal", "WasteRecord", w.id)
    db.commit(); db.refresh(r)
    return r


def approve_disposal(db, rid: int, current: User) -> WasteDisposalRequest:
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


def reject_disposal(db, rid: int, current: User) -> WasteDisposalRequest:
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


def mark_disposed(db, rid: int, current: User) -> WasteDisposalRequest:
    r, w = _disposal_request_for_update(db, rid)
    if r.status != "approved": raise HTTPException(400, "Disposal not approved yet")
    _require_disposal_waste(w, "disposal_approved")
    r.status = "disposed"
    w.status = "disposed"
    log_action(db, current, "mark_disposed", "WasteDisposalRequest", r.id)
    db.commit(); db.refresh(r)
    return r
