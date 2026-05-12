from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Item, StockBatch, StockMovement, Warehouse


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


def stock_summary(db: Session, category: str | None = None) -> list[dict]:
    q = db.query(Item)
    if category:
        q = q.filter(Item.category == category)
    out = []
    for it in q.all():
        qty = current_stock_for_item(db, it.id)
        out.append({
            "item_id": it.id,
            "sku": it.sku,
            "name": it.name,
            "category": it.category,
            "unit": it.unit,
            "quantity": qty,
        })
    return out
