"""Use ECO fabric at ECT without debiting its central identity twice.

The existing central batch ID remains the planning/material identity. Only an
authoritative EcoMaterialBatch.source_stock_batch_id link selects the physical
ECO ledger, including zero-balance direct-receipt identities created by explicit
Planning/passport saves. Legacy ECT central stock retains its existing path.
Callers own authorization, order/record locks, rollback and commit.
"""
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.enums.eco_inventory import EcoMaterialMovementKind
from app.models.factory_scope_service import require_factory_access, selected_factory_code
from app.models.inventory.eco_inventory_service import quality_passed
from app.schemas import CuttingRecord, Department, ProductionOrder, StockBatch, User, WorkOrder
from app.schemas.inventory import eco_inventory_persistence as persistence
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement

REVERSAL_REFERENCE = "ECTCuttingConsumptionReversal"


def is_ect_order(db: Session, production_order_id: int) -> bool:
    return db.query(WorkOrder.id).join(Department, Department.id == WorkOrder.department_id).join(
        ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id,
    ).filter(WorkOrder.production_order_id == production_order_id, WorkOrder.operation == "cutting",
             Department.code == "ECT", ProductionOrder.source_type != "usluga").first() is not None


def transferred_fabric_rows(db: Session, production_order_id: int, stock_batch_id: int, *, lock=False):
    """None means use the existing central path; an empty balance never does."""
    if not is_ect_order(db, production_order_id):
        return None
    query = db.query(EcoMaterialBatch).filter(EcoMaterialBatch.kind == "fabric",
        EcoMaterialBatch.source_stock_batch_id == stock_batch_id).order_by(EcoMaterialBatch.id)
    if lock:
        db.flush()
        query = query.with_for_update(of=EcoMaterialBatch).populate_existing()
    rows = query.all()
    if not rows:
        return None
    source = db.get(StockBatch, stock_batch_id)
    if not source or any(row.item_id != source.item_id or row.unit != source.unit for row in rows):
        raise HTTPException(409, "Transferred fabric identity or unit has changed; review its receipt")
    return rows


def available_transferred_fabric(rows) -> Decimal:
    return sum((Decimal(str(row.quantity)) - Decimal(str(row.reserved_quantity or 0))
                for row in rows if quality_passed(row)), Decimal(0))


def transferred_fabric_balance(db: Session, production_order_id: int, stock_batch_id: int):
    rows = transferred_fabric_rows(db, production_order_id, stock_batch_id)
    return None if rows is None else available_transferred_fabric(rows)


def transferred_fabric_balances(db: Session, production_order_id: int, batches: dict[int, StockBatch]) -> dict[int, Decimal]:
    """One ECT-scoped receipt query for preloaded authoritative central sources.

    A mapped zero/held balance stays present: only an absent mapping permits the
    legacy central path. Callers keep their existing order/factory authorization.
    """
    if not batches:
        return {}
    ect_order = db.query(WorkOrder.id).join(Department, Department.id == WorkOrder.department_id).join(
        ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id,
    ).filter(WorkOrder.production_order_id == production_order_id, WorkOrder.operation == "cutting",
             Department.code == "ECT", ProductionOrder.source_type != "usluga").exists()
    grouped = defaultdict(list)
    for row in db.query(EcoMaterialBatch).filter(EcoMaterialBatch.kind == "fabric",
            EcoMaterialBatch.source_stock_batch_id.in_(sorted(batches)), ect_order).order_by(EcoMaterialBatch.id).all():
        source = batches[row.source_stock_batch_id]
        if row.item_id != source.item_id or row.unit != source.unit:
            raise HTTPException(409, "Transferred fabric identity or unit has changed; review its receipt")
        grouped[source.id].append(row)
    return {source_id: available_transferred_fabric(rows) for source_id, rows in grouped.items()}


def list_transferred_passport_fabrics(db: Session, current: User, production_order_id: int, q: str = "", item_id: int | None = None) -> list[dict]:
    """Small cutting lookup; no ECO row IDs are exposed as central batch IDs."""
    require_factory_access(current, "ECO")
    if not is_ect_order(db, production_order_id):
        raise HTTPException(400, "Select an Eco Cotton cutting order")
    from app.models.production.eco_fabric_source_service import eco_fabric_options
    return eco_fabric_options(db, q=q, item_id=item_id)


def list_passport_fabrics(db: Session, current: User, production_order_id: int, q: str = "", item_id: int | None = None) -> list[dict]:
    """Caller first authorizes the selected production order's cutting work."""
    from app.models.inventory.stock_service import list_batches
    allowed = ("id", "item_id", "item_name", "item_sku", "item_category", "image_url", "batch_no", "internal_batch_no", "color", "unit",
               "width", "gsm", "warehouse_name", "quantity", "reserved_quantity", "available_quantity")
    central = [{key: row.get(key) for key in allowed} for row in
        list_batches(db, current, group="materials", hide_empty=True, page_size=500, q=q, item_id=item_id)]
    if not is_ect_order(db, production_order_id):
        return central
    transferred = list_transferred_passport_fabrics(db, current, production_order_id, q, item_id)
    # A depleted/held transferred receipt must never fall back to Milana stock.
    linked_ids = {row[0] for row in db.query(EcoMaterialBatch.source_stock_batch_id).filter(
        EcoMaterialBatch.kind == "fabric", EcoMaterialBatch.source_stock_batch_id.isnot(None)).distinct()}
    return transferred + [row for row in central if row["id"] not in linked_ids]


def _ect_record(db, reference_type, reference_id):
    if reference_type != "CuttingRecord" or reference_id is None:
        return None
    return db.query(CuttingRecord, WorkOrder).join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id).join(
        Department, Department.id == WorkOrder.department_id,
    ).filter(CuttingRecord.id == reference_id, WorkOrder.operation == "cutting", Department.code == "ECT").first()


def eco_cutting_actor(db: Session, user_id: int | None, reference_type: str) -> bool:
    # The request's actor is already in this Session's identity map. MIL/BST and
    # unrelated ledger calls retain their existing query cost and stock path.
    if reference_type != "CuttingRecord" or user_id is None:
        return False
    actor = db.get(User, user_id)
    return actor is not None and selected_factory_code(actor) == "ECO"


def consume_transferred_fabric(db: Session, *, stock_batch_id: int, quantity, unit: str,
                               reference_type: str, reference_id: int | None, user_id: int | None) -> bool:
    """Return True only when this CuttingRecord owns a transferred ECO debit."""
    if not eco_cutting_actor(db, user_id, reference_type):
        return False
    context = _ect_record(db, reference_type, reference_id)
    if context is None:
        return False
    record, work = context
    rows = transferred_fabric_rows(db, work.production_order_id, stock_batch_id, lock=True)
    if rows is None:
        return False
    actor = db.get(User, user_id) if user_id else None
    if actor is None:
        raise HTTPException(403, "A cutting operator is required for Eco Cotton fabric consumption")
    require_factory_access(actor, "ECO")
    amount = Decimal(str(quantity))
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.0001")):
        raise HTTPException(400, "Fabric consumption must be positive with at most four decimal places")
    if any(row.unit != unit for row in rows):
        raise HTTPException(400, "Cutting material unit must match the transferred fabric unit")
    available = available_transferred_fabric(rows)
    if amount > available:
        raise HTTPException(409, f"Insufficient transferred Eco Cotton fabric: available {available:g} {unit}; required {amount:g} {unit}")
    left = amount
    for row in rows:
        take = min(left, available_transferred_fabric([row]))
        if take <= 0:
            continue
        persistence.set_batch_balance(db, row, quantity=Decimal(str(row.quantity)) - take,
                                      reserved_quantity=Decimal(str(row.reserved_quantity or 0)))
        persistence.insert_movement(db, batch_id=row.id, kind=EcoMaterialMovementKind.CONSUME,
            quantity=take, created_by=actor.id, production_order_id=work.production_order_id,
            reference_type="CuttingRecord", reference_id=record.id,
            notes=f"ECT cutting; Milana source batch {stock_batch_id}")
        left -= take
        if left == 0:
            break
    return True


def cutting_eco_consumption(db: Session, record_ids: list[int], *, lock=False):
    """Proven active physical debits grouped by the existing central identity."""
    if not record_ids:
        return {}, []
    query = db.query(EcoMaterialMovement).filter(EcoMaterialMovement.reference_type == "CuttingRecord",
        EcoMaterialMovement.reference_id.in_(record_ids)).order_by(EcoMaterialMovement.id)
    if lock:
        query = query.with_for_update(of=EcoMaterialMovement).populate_existing()
    movements = query.all()
    reversed_ids = {row[0] for row in db.query(EcoMaterialMovement.reference_id).filter(
        EcoMaterialMovement.reference_type == REVERSAL_REFERENCE,
        EcoMaterialMovement.reference_id.in_([row.id for row in movements])).all()} if movements else set()
    result = defaultdict(Decimal)
    for movement in movements:
        if movement.id in reversed_ids:
            raise HTTPException(409, "Eco Cotton cutting fabric has already been reversed; review its history")
        batch = db.get(EcoMaterialBatch, movement.batch_id)
        source = db.get(StockBatch, batch.source_stock_batch_id) if batch and batch.source_stock_batch_id else None
        context = _ect_record(db, "CuttingRecord", movement.reference_id)
        if (movement.kind != "consume" or not batch or not source or batch.kind != "fabric"
                or source.item_id != batch.item_id or source.unit != batch.unit or context is None
                or context[1].production_order_id != movement.production_order_id):
            raise HTTPException(409, "Eco Cotton cutting movement identity needs review before deletion")
        result[(movement.reference_id, source.id, batch.unit)] += Decimal(str(movement.quantity))
    return dict(result), movements


def reverse_cutting_eco_consumption(db: Session, movements, current: User):
    """Caller has validated all expected usage and holds record/order locks."""
    if not movements:
        return
    require_factory_access(current, "ECO")
    rows = {row.id: row for row in db.query(EcoMaterialBatch).filter(
        EcoMaterialBatch.id.in_({movement.batch_id for movement in movements})).order_by(EcoMaterialBatch.id)
        .with_for_update(of=EcoMaterialBatch).populate_existing().all()}
    for movement in movements:
        row = rows[movement.batch_id]
        persistence.set_batch_balance(db, row, quantity=Decimal(str(row.quantity)) + Decimal(str(movement.quantity)),
                                      reserved_quantity=Decimal(str(row.reserved_quantity or 0)))
        persistence.insert_movement(db, batch_id=row.id, kind=EcoMaterialMovementKind.RECEIVE,
            quantity=Decimal(str(movement.quantity)), created_by=current.id,
            production_order_id=movement.production_order_id, reference_type=REVERSAL_REFERENCE,
            reference_id=movement.id, notes=f"Reversal of deleted ECT CuttingRecord {movement.reference_id}")
