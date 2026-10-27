"""Material and fabric transfers: stock movements between warehouses, and the Eco
Cotton register for fabric sent offsite.

Stock truth (reserved/available quantities) stays in `app.models.inventory_service`;
the roll-code parser and the Tashkent business date live in
`app.models.inventory.fabric_scans_service`.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import defer, lazyload

from app.libs.dto.inventory.eco_fabric_transfer_input import ReturnIn, ScanIn, SendIn
from app.libs.enums.inventory import StockMovementType
from app.libs.dto.inventory.stock_movement_input import StockMovementIn
from app.libs.dto.inventory.stock_movement_output import StockMovementOut
from app.models import inventory_access_service as inventory_access
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.inventory.fabric_scans_service import TASHKENT, parse_roll
from app.models.inventory_service import (
    available_reservation_item_capacity,
    available_stock_for_item,
    reserved_stock_for_batch,
)
from app.models.inventory.stock_service import _locked_stock_batch_statement
from app.models.workflow_service import archive_depleted_material_batch
from app.schemas.inventory import stock_movement_persistence
from app.schemas import (
    EcoFabricDispatch,
    EcoFabricRoll,
    Item,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
)


# The movement kinds this operation accepts. The canonical vocabulary is
# larger; the other kinds keep their own writers.
_TRANSFER_MOVEMENT_TYPES = (
    StockMovementType.TRANSFER,
    StockMovementType.ISSUE,
    StockMovementType.CONSUME,
    StockMovementType.ADJUSTMENT,
    StockMovementType.RETURN,
)
_OUTGOING_MOVEMENT_TYPES = (
    StockMovementType.ISSUE,
    StockMovementType.CONSUME,
    StockMovementType.TRANSFER,
)


# ===== Material transfer =====
def transfer_stock(
    db,
    payload: StockMovementIn,
    current: User,
    idempotency_key: str | None = None,
) -> dict:
    inventory_access.require_item(db, current, payload.item_id)
    inventory_access.require_batch(db, current, payload.batch_id)
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.transfer", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    if payload.movement_type not in _TRANSFER_MOVEMENT_TYPES:
        raise HTTPException(400, "Invalid movement_type")
    quantity = Decimal(str(payload.quantity))
    if not quantity.is_finite() or quantity <= 0 or quantity >= Decimal("10000000000"):
        raise HTTPException(400, "Quantity must be finite, positive and less than 10000000000")
    if quantity != quantity.quantize(Decimal("0.0001")):
        raise HTTPException(400, "Quantity must have at most four decimal places")
    item = db.get(Item, payload.item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    if payload.unit != item.unit:
        raise HTTPException(409, "Movement unit must match the item unit")
    for warehouse_id in (payload.from_warehouse_id, payload.to_warehouse_id):
        if warehouse_id is not None and not db.get(Warehouse, warehouse_id):
            raise HTTPException(404, "Warehouse not found")

    movement_data = payload.model_dump()
    movement_data["quantity"] = quantity
    if payload.batch_id is not None:
        # Lock the batch before reading its quantity, warehouse or claims so a
        # concurrent movement or reservation cannot be validated against a
        # stale row. The ledger write and the batch write share this
        # transaction, so the two either both land or neither does.
        batch = db.execute(
            _locked_stock_batch_statement(payload.batch_id).execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if not batch:
            raise HTTPException(404, "Active stock batch not found")
        if batch.item_id != item.id:
            raise HTTPException(409, "Stock batch does not belong to the selected item")
        if payload.unit != batch.unit:
            raise HTTPException(409, "Movement unit must match the batch unit")
        if db.query(EcoFabricRoll.id).filter_by(batch_id=batch.id, returned_at=None).first():
            raise HTTPException(409, "Return outstanding fabric through the Eco Cotton register before changing this batch")

        outgoing = payload.movement_type in _OUTGOING_MOVEMENT_TYPES
        warehouse_field = "from_warehouse_id" if outgoing else "to_warehouse_id"
        movement_warehouse_id = movement_data[warehouse_field]
        if movement_warehouse_id is not None and movement_warehouse_id != batch.warehouse_id:
            raise HTTPException(409, "Movement warehouse must match the batch warehouse")
        movement_data[warehouse_field] = batch.warehouse_id

        if outgoing:
            # Match reservation creation's batch-before-item lock order. Item-only
            # claims can commit while the batch is locked, so read all capacity
            # only after taking the common item lock as well.
            db.execute(
                select(Item).where(Item.id == item.id)
                .with_for_update(of=Item, key_share=True)
                .execution_options(populate_existing=True)
            ).scalar_one()
            reserved = Decimal(str(reserved_stock_for_batch(db, batch.id)))
            item_capacity = Decimal(str(available_reservation_item_capacity(db, item.id, batch.warehouse_id))).quantize(
                Decimal("0.0001"),
            )
            if quantity > min(batch.quantity - reserved, item_capacity):
                raise HTTPException(409, "Movement quantity exceeds available batch stock")
            if payload.movement_type is StockMovementType.TRANSFER:
                if payload.to_warehouse_id is None:
                    raise HTTPException(400, "Destination warehouse is required")
                if payload.to_warehouse_id == batch.warehouse_id:
                    raise HTTPException(400, "Destination warehouse must differ from the source")
                # A batch has one location. A partial relocation needs a separate
                # batch identity, which this endpoint does not create.
                if quantity != batch.quantity:
                    raise HTTPException(409, "Only the entire unreserved batch can be transferred")
                batch.warehouse_id = payload.to_warehouse_id
            else:
                batch.quantity -= quantity
                archive_depleted_material_batch(db, batch, user_id=current.id)
        else:
            if batch.quantity + quantity >= Decimal("10000000000"):
                raise HTTPException(400, "Resulting batch quantity is too large")
            batch.quantity += quantity
    elif payload.movement_type in _OUTGOING_MOVEMENT_TYPES:
        db.execute(
            select(Item).where(Item.id == item.id)
            .with_for_update(of=Item, key_share=True)
            .execution_options(populate_existing=True)
        ).scalar_one()
        available = Decimal(str(available_reservation_item_capacity(db, item.id, payload.from_warehouse_id))).quantize(
            Decimal("0.0001"),
        )
        if quantity > available:
            raise HTTPException(409, "Movement quantity exceeds available item stock")

    mv = stock_movement_persistence.insert_stock_movement(
        db,
        movement_type=payload.movement_type,
        item_id=payload.item_id,
        batch_id=payload.batch_id,
        from_warehouse_id=movement_data["from_warehouse_id"],
        to_warehouse_id=movement_data["to_warehouse_id"],
        quantity=quantity,
        unit=payload.unit,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        created_by=current.id,
    )
    log_action(db, current, payload.movement_type.value, "StockMovement", mv.id)
    response = StockMovementOut.model_validate(mv).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="inventory.transfer",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit(); db.refresh(mv)
    return response


# ===== Eco Cotton fabric register =====
def eco_batch_lock(db, batch_id: int) -> StockBatch:
    batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=batch_id).with_for_update().first()
    if not batch or not batch.item or batch.item.category not in inventory_access.MATERIAL_CATEGORIES:
        raise HTTPException(404, "fabricScans.fabric_not_found")
    return batch


def eco_roll_quantity(db, batch: StockBatch, roll: int) -> tuple[Decimal, list]:
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


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def eco_roll_data(row: EcoFabricRoll) -> dict:
    return {"id": row.id, "dispatch_id": row.dispatch_id, "code": f"B{row.batch_id}-R{row.roll_number}",
            "fabric_name": row.fabric_name, "batch_no": row.batch_no, "color": row.color,
            "roll_number": row.roll_number, "quantity": row.quantity, "unit": row.unit,
            "returned_at": _utc(row.returned_at), "return_operator_name": row.return_operator_name}


def eco_dispatch_data(db, dispatch: EcoFabricDispatch, *, rows=None) -> dict:
    if rows is None:
        rows = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch.id).order_by(EcoFabricRoll.id).all()
    return {"id": dispatch.id, "number": f"ECO-{dispatch.id:06d}", "sent_at": _utc(dispatch.sent_at),
            "operator_name": dispatch.operator_name, "rows": [eco_roll_data(row) for row in rows],
            "sent_rolls": len(rows), "outstanding_rolls": sum(row.returned_at is None for row in rows),
            "sent_kg": sum(Decimal(row.quantity) for row in rows),
            "outstanding_kg": sum(Decimal(row.quantity) for row in rows if row.returned_at is None)}


def eco_scan_roll(db, payload: ScanIn) -> dict:
    batch_id, roll = parse_roll(payload.code)
    batch = eco_batch_lock(db, batch_id)
    outstanding = db.query(EcoFabricRoll).filter_by(batch_id=batch_id, roll_number=roll, returned_at=None).first()
    if outstanding:
        return {**eco_roll_data(outstanding), "status": "sent"}
    amount, _ = eco_roll_quantity(db, batch, roll)
    if batch.archived_at or Decimal(batch.quantity) < amount:
        raise HTTPException(409, "ecoTransfers.unavailable")
    return {"code": f"B{batch_id}-R{roll}", "status": "available", "fabric_name": batch.item.name,
            "batch_no": batch.batch_no, "color": batch.color, "roll_number": roll, "quantity": amount, "unit": batch.unit}


def eco_send_fabric(db, payload: SendIn, user: User) -> dict:
    identities = sorted(set(parse_roll(code) for code in payload.codes))
    if len(identities) != len(payload.codes):
        raise HTTPException(400, "ecoTransfers.duplicate")
    # Lock batches in stable order; all mutation paths share the inventory row locks.
    batches = {bid: eco_batch_lock(db, bid) for bid in sorted({bid for bid, _ in identities})}
    key = str(payload.request_key)
    previous = db.query(EcoFabricDispatch).filter_by(request_key=key).first()
    if previous:
        old = db.query(EcoFabricRoll).filter_by(dispatch_id=previous.id).all()
        if sorted((r.batch_id, r.roll_number) for r in old) != identities:
            raise HTTPException(409, "ecoTransfers.changedRequest")
        return eco_dispatch_data(db, previous)
    dispatch = EcoFabricDispatch(request_key=key, created_by=user.id, operator_name=user.name,
                                  sent_at=datetime.now(timezone.utc), remaining_inventory=[])
    db.add(dispatch)
    db.flush()
    for bid, roll in identities:
        batch = batches[bid]
        if db.query(EcoFabricRoll.id).filter_by(batch_id=bid, roll_number=roll, returned_at=None).first():
            raise HTTPException(409, "ecoTransfers.alreadySent")
        amount, weights = eco_roll_quantity(db, batch, roll)
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
            Item.category.in_(inventory_access.MATERIAL_CATEGORIES), StockBatch.archived_at.is_(None), StockBatch.quantity > 0,
        ).order_by(Item.name, StockBatch.batch_no, StockBatch.id).all()]
    result = eco_dispatch_data(db, dispatch)
    log_action(db, user, "send", "EcoFabricDispatch", dispatch.id, new_value=result)
    db.commit()
    return result


def eco_return_fabric(db, payload: ReturnIn, user: User) -> dict:
    bid, roll = parse_roll(payload.code)
    batch = eco_batch_lock(db, bid)
    previous = db.query(EcoFabricRoll).filter_by(return_key=str(payload.request_key)).first()
    if previous:
        if (previous.batch_id, previous.roll_number, previous.dispatch_id) != (bid, roll, payload.dispatch_id):
            raise HTTPException(409, "ecoTransfers.changedRequest")
        return eco_roll_data(previous)
    if payload.dispatch_id > 2_147_483_647:
        raise HTTPException(409, "ecoTransfers.notSent")
    row = db.query(EcoFabricRoll).filter_by(batch_id=bid, roll_number=roll,
                    dispatch_id=payload.dispatch_id).with_for_update().first()
    if not row or row.returned_at is not None:
        raise HTTPException(409, "ecoTransfers.notSent")
    if batch.unit != row.unit or not batch.item.is_active:
        raise HTTPException(409, "ecoTransfers.batchChanged")
    before = eco_roll_data(row)
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
    log_action(db, user, "return", "EcoFabricRoll", row.id, old_value=before, new_value=eco_roll_data(row))
    db.commit()
    return eco_roll_data(row)


def eco_transfer_report(db, report_date: date | None = None, page: int = 1, page_size: int = 30) -> dict:
    query = db.query(EcoFabricDispatch)
    if report_date:
        start = datetime.combine(report_date, time.min, TASHKENT).astimezone(timezone.utc)
        query = query.filter(EcoFabricDispatch.sent_at >= start, EcoFabricDispatch.sent_at < start + timedelta(days=1))
    outstanding = db.query(func.count(EcoFabricRoll.id), func.coalesce(func.sum(EcoFabricRoll.quantity), 0)).filter_by(returned_at=None).one()
    # The history page never serialises the immutable remaining-inventory snapshot, so defer it.
    # raiseload=True: a plain defer() would silently re-fetch per dispatch, reintroducing the
    # N+1 this batching removes. This makes any future read of it here fail loudly instead.
    rows = query.options(defer(EcoFabricDispatch.remaining_inventory, raiseload=True)).order_by(
        EcoFabricDispatch.sent_at.desc(), EcoFabricDispatch.id.desc(),
    ).offset((page-1)*page_size).limit(page_size).all()
    rolls_by_dispatch = {row.id: [] for row in rows}
    if rows:
        for roll in db.query(EcoFabricRoll).filter(
            EcoFabricRoll.dispatch_id.in_(list(rolls_by_dispatch)),
        ).order_by(EcoFabricRoll.id).all():
            rolls_by_dispatch[roll.dispatch_id].append(roll)
    return {"total": query.count(), "outstanding_rolls": outstanding[0], "outstanding_kg": outstanding[1],
            "items": [eco_dispatch_data(db, row, rows=rolls_by_dispatch[row.id]) for row in rows]}


def eco_transfer_pdf(db, dispatch_id: int, lang: str = "en") -> dict:
    from app.models.eco_transfer_pdf_service import build_pdf

    dispatch = db.get(EcoFabricDispatch, dispatch_id)
    if not dispatch:
        raise HTTPException(404, "Not found")
    data = eco_dispatch_data(db, dispatch)
    return {"number": data["number"], "content": build_pdf(data, lang=lang)}
