"""Planning service: calculate material requirements from BOM and stock."""
from sqlalchemy.orm import Session

from app.models import Model, ModelBOM, Item, SalesOrder, SalesOrderItem
from app.services.inventory import current_stock_for_item


def material_requirements_for_sales_order(db: Session, sales_order_id: int) -> list[dict]:
    """For each SO line, expand BOM, compute required = qty * qty_per_piece * (1 + waste%).

    Returns aggregated list per item with required vs available and shortage.
    """
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return []

    agg: dict[int, dict] = {}
    for line in so.items:
        bom_lines = db.query(ModelBOM).filter(ModelBOM.model_id == line.model_id).all()
        for b in bom_lines:
            # match on size/color if BOM specifies them
            if b.size and b.size != line.size:
                continue
            if b.color and b.color != line.color:
                continue
            required = float(b.quantity_per_piece) * line.quantity * (1.0 + float(b.waste_percent) / 100.0)
            if b.item_id not in agg:
                item = db.get(Item, b.item_id)
                agg[b.item_id] = {
                    "item_id": b.item_id,
                    "sku": item.sku if item else "",
                    "name": item.name if item else "",
                    "unit": b.unit,
                    "required_quantity": 0.0,
                    "available_quantity": 0.0,
                    "shortage": 0.0,
                }
            agg[b.item_id]["required_quantity"] += required

    for item_id, row in agg.items():
        avail = current_stock_for_item(db, item_id)
        row["available_quantity"] = avail
        row["shortage"] = max(0.0, row["required_quantity"] - avail)

    return list(agg.values())


def material_requirements_for_quantity(db: Session, model_id: int, items: list[dict]) -> list[dict]:
    """items: [{color, size, quantity}, ...]"""
    agg: dict[int, dict] = {}
    bom_lines = db.query(ModelBOM).filter(ModelBOM.model_id == model_id).all()
    for line in items:
        for b in bom_lines:
            if b.size and b.size != line.get("size"):
                continue
            if b.color and b.color != line.get("color"):
                continue
            required = float(b.quantity_per_piece) * int(line.get("quantity", 0)) * (1.0 + float(b.waste_percent) / 100.0)
            if b.item_id not in agg:
                item = db.get(Item, b.item_id)
                agg[b.item_id] = {
                    "item_id": b.item_id,
                    "sku": item.sku if item else "",
                    "name": item.name if item else "",
                    "unit": b.unit,
                    "required_quantity": 0.0,
                    "available_quantity": 0.0,
                    "shortage": 0.0,
                }
            agg[b.item_id]["required_quantity"] += required

    for item_id, row in agg.items():
        avail = current_stock_for_item(db, item_id)
        row["available_quantity"] = avail
        row["shortage"] = max(0.0, row["required_quantity"] - avail)

    return list(agg.values())
