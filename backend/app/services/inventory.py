from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Item, StockBatch, StockMovement, Warehouse

MATERIAL_CATEGORIES = ("fabric", "semi_finished")
ACCESSORY_CATEGORIES = ("accessory", "packaging")


def categories_for_group(group: str | None) -> tuple[str, ...] | None:
    if not group:
        return None
    normalized = group.strip().lower()
    if normalized in {"material", "materials"}:
        return MATERIAL_CATEGORIES
    if normalized in {"accessory", "accessories"}:
        return ACCESSORY_CATEGORIES
    return None


def current_stock_for_item(db: Session, item_id: int, warehouse_id: int | None = None) -> float:
    """Compute on-hand stock for an item: sum of batches in warehouse minus issues out.

    For MVP: stock = sum(StockBatch.quantity in warehouse) + net of stock_movements where
    item matches and movements are receive/produce vs issue/consume/waste/shipment.
    """
    # Sum of batches (initial received) for the item — optionally filtered to warehouse
    bq = db.query(func.coalesce(func.sum(StockBatch.quantity), 0)).filter(StockBatch.item_id == item_id)
    if warehouse_id is not None:
        bq = bq.filter(StockBatch.warehouse_id == warehouse_id)
    batch_total = float(bq.scalar() or 0)

    # Sum movements: receives/produces add, issues/consumes/waste/shipments subtract
    # Note: receive movements that already correspond to batches are NOT double counted
    # because batches represent the canonical receive; we count only post-receipt activity.
    movements = db.query(StockMovement.movement_type, func.coalesce(func.sum(StockMovement.quantity), 0)) \
        .filter(StockMovement.item_id == item_id) \
        .group_by(StockMovement.movement_type).all()

    delta = 0.0
    out_types = {"issue", "consume", "waste", "shipment"}
    in_types = {"produce", "return", "adjustment"}
    for mt, qty in movements:
        q = float(qty or 0)
        if mt in out_types:
            delta -= q
        elif mt in in_types:
            delta += q
    return batch_total + delta


def stock_summary(
    db: Session,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
) -> list[dict]:
    query = db.query(Item)
    categories = categories_for_group(group)
    if categories:
        query = query.filter(Item.category.in_(categories))
    if category:
        query = query.filter(Item.category == category)
    search = (q or "").strip()
    if search:
        term = f"%{search}%"
        query = query.filter((Item.sku.ilike(term)) | (Item.name.ilike(term)) | (Item.unit.ilike(term)))
    items = query.all()
    if not items:
        return []

    item_ids = [it.id for it in items]
    batch_rows = (
        db.query(StockBatch.item_id, func.coalesce(func.sum(StockBatch.quantity), 0))
        .filter(StockBatch.item_id.in_(item_ids))
        .group_by(StockBatch.item_id)
        .all()
    )
    move_rows = (
        db.query(StockMovement.item_id, StockMovement.movement_type, func.coalesce(func.sum(StockMovement.quantity), 0))
        .filter(StockMovement.item_id.in_(item_ids))
        .group_by(StockMovement.item_id, StockMovement.movement_type)
        .all()
    )

    batch_totals = {int(item_id): float(qty or 0) for item_id, qty in batch_rows}
    deltas: dict[int, float] = {int(i): 0.0 for i in item_ids}
    out_types = {"issue", "consume", "waste", "shipment"}
    in_types = {"produce", "return", "adjustment"}
    for item_id, movement_type, qty in move_rows:
        qv = float(qty or 0)
        iid = int(item_id)
        if movement_type in out_types:
            deltas[iid] = deltas.get(iid, 0.0) - qv
        elif movement_type in in_types:
            deltas[iid] = deltas.get(iid, 0.0) + qv

    out = []
    for it in items:
        qty = batch_totals.get(it.id, 0.0) + deltas.get(it.id, 0.0)
        out.append({
            "item_id": it.id,
            "sku": it.sku,
            "name": it.name,
            "category": it.category,
            "unit": it.unit,
            "quantity": qty,
        })
    return out
