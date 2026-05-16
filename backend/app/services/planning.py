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


def planning_estimate_for_sales_order(db: Session, sales_order_id: int) -> dict | None:
    """Build planning estimate for sales approval loop.

    Returns material usage + cost estimate and rough lead-time estimate.
    """
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return None

    material_rows = material_requirements_for_sales_order(db, sales_order_id)
    estimated_material_cost = 0.0
    enriched_materials: list[dict] = []
    for row in material_rows:
        item = db.get(Item, row["item_id"])
        unit_cost = float(item.default_cost or 0) if item else 0.0
        est_cost = float(row["required_quantity"] or 0) * unit_cost
        estimated_material_cost += est_cost
        enriched_materials.append(
            {
                **row,
                "category": getattr(item, "category", None) if item else None,
                "unit_cost": unit_cost,
                "estimated_cost": est_cost,
            }
        )

    total_qty = 0
    estimated_minutes = 0.0
    for line in so.items:
        qty = int(line.quantity or 0)
        total_qty += qty
        model = db.get(Model, line.model_id)
        if not model:
            continue
        estimated_minutes += float(model.sam_minutes or 0) * qty

    return {
        "sales_order_id": so.id,
        "estimated_material_cost": estimated_material_cost,
        "estimated_sales_value": float(so.total_amount or 0),
        "estimated_lead_time_minutes": int(round(estimated_minutes)),
        "estimated_lead_time_hours": round(estimated_minutes / 60.0, 2),
        "total_quantity": total_qty,
        "materials": enriched_materials,
    }
