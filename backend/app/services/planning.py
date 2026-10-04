"""Planning service: calculate material requirements from BOM and stock."""
from types import SimpleNamespace

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import (
    Item,
    MaterialReservation,
    Model,
    ModelBOM,
    SalesOrder,
    SalesOrderItem,
    StockBatch,
    StockMovement,
)
from app.services.inventory import ACTIVE_RESERVATION_STATUSES, available_stock_for_item

# Planning reads are batched so that an order with N lines and M materials costs
# a fixed number of round trips per dimension instead of one per line or item.
# The chunk size keeps the `IN (...)` bind lists comfortably inside PostgreSQL's
# parameter limit.
_QUERY_CHUNK_SIZE = 400

# Same movement classification as inventory.current_stock_for_item.
_STOCK_OUT_TYPES = ("issue", "consume", "waste", "shipment")
_STOCK_IN_TYPES = ("produce", "return", "adjustment")


def _int_or_none(value) -> int | None:
    return int(value) if value is not None else None


def _chunks(values):
    """Deduplicated, order-stable chunks of the non-null ids in `values`."""
    ordered = sorted({_int_or_none(value) for value in values} - {None})
    for start in range(0, len(ordered), _QUERY_CHUNK_SIZE):
        yield ordered[start:start + _QUERY_CHUNK_SIZE]


def _bom_by_model(db: Session, model_ids) -> dict[int, list[ModelBOM]]:
    """BOM rows for every requested model, one statement per chunk.

    Rows are ordered by primary key so each model's list matches the order a
    single-model query yields, keeping the aggregated result order and the
    per-material `unit` selection unchanged.
    """
    grouped: dict[int, list[ModelBOM]] = {}
    for chunk in _chunks(model_ids):
        rows = db.query(ModelBOM).filter(ModelBOM.model_id.in_(chunk)).order_by(ModelBOM.id).all()
        for row in rows:
            grouped.setdefault(int(row.model_id), []).append(row)
    return grouped


def _rows_by_id(db: Session, entity, ids) -> dict[int, object]:
    """Rows of `entity` for the requested ids, one statement per chunk.

    Replaces the per-row `Session.get` lookups with a single bounded read; a row
    missing from the map is the same `None` that `Session.get` would have
    returned for a missing primary key.
    """
    return {
        int(row.id): row
        for chunk in _chunks(ids)
        for row in db.query(entity).filter(entity.id.in_(chunk)).all()
    }


def _available_stock_for_items(db: Session, item_ids) -> dict[int | None, float]:
    """Batched equivalent of `available_stock_for_item` for the global balance.

    Per item this is the same arithmetic: batch balances plus the applicable
    batchless ledger movements, minus the active reservation claim, which is
    floored at zero on its own. All quantity columns are exact decimals, so
    grouping by item sums the same rows to the same totals as summing per item.
    """
    raw_ids = set(item_ids)
    result: dict[int | None, float] = {}
    for chunk in _chunks(raw_ids):
        batch_totals = dict(
            db.query(StockBatch.item_id, func.coalesce(func.sum(StockBatch.quantity), 0))
            .filter(StockBatch.item_id.in_(chunk))
            .group_by(StockBatch.item_id)
            .all()
        )
        movement_totals = {
            int(item_id): (float(incoming or 0), float(outgoing or 0))
            for item_id, incoming, outgoing in db.query(
                StockMovement.item_id,
                func.coalesce(
                    func.sum(
                        case(
                            (StockMovement.movement_type.in_(_STOCK_IN_TYPES), StockMovement.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (StockMovement.movement_type.in_(_STOCK_OUT_TYPES), StockMovement.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .filter(StockMovement.item_id.in_(chunk), StockMovement.batch_id.is_(None))
            .group_by(StockMovement.item_id)
            .all()
        }
        reserved_totals = dict(
            db.query(
                MaterialReservation.item_id,
                func.coalesce(
                    func.sum(
                        MaterialReservation.reserved_quantity
                        - MaterialReservation.consumed_quantity
                        - MaterialReservation.released_quantity
                    ),
                    0,
                ),
            )
            .filter(
                MaterialReservation.item_id.in_(chunk),
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
            .group_by(MaterialReservation.item_id)
            .all()
        )
        for item_id in chunk:
            incoming, outgoing = movement_totals.get(item_id, (0.0, 0.0))
            reserved = max(0.0, float(reserved_totals.get(item_id) or 0))
            result[item_id] = float(batch_totals.get(item_id) or 0) + incoming - outgoing - reserved
    # A BOM row may name a material without an item. Keep the single-item path
    # for that degenerate key so its balance is read exactly as before.
    if None in raw_ids:
        result[None] = available_stock_for_item(db, None)
    return result


def _item_composition(item: Item | None) -> list[dict]:
    if not item:
        return []
    rows = item.composition_json or []
    if not isinstance(rows, list):
        return []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            percentage = float(row.get("percentage") or 0)
        except (TypeError, ValueError):
            percentage = 0.0
        out.append({"name": name, "percentage": percentage})
    return out


def _requirements_from_lines(db: Session, lines) -> list[dict]:
    """Expand the BOM of each line and price the aggregate against stock.

    `lines` only need `model_id`, `size`, `color` and `quantity` attributes.
    Each dimension is read once: BOM for the distinct models, available stock
    for the distinct materials, so the statement count does not depend on how
    many lines were passed in.
    """
    agg: dict[int, dict] = {}
    bom_by_model = _bom_by_model(db, (line.model_id for line in lines))
    for line in lines:
        for b in bom_by_model.get(_int_or_none(line.model_id), ()):
            # match on size/color if BOM specifies them
            if b.size and b.size != line.size:
                continue
            if b.color and b.color != line.color:
                continue
            required = float(b.quantity_per_piece) * int(line.quantity or 0)
            if b.item_id not in agg:
                # ModelBOM.item is eager-joined, so the material comes with the
                # BOM statement instead of costing a lookup per item.
                item = b.item
                agg[b.item_id] = {
                    "item_id": b.item_id,
                    "sku": item.sku if item else "",
                    "name": item.name if item else "",
                    "composition": _item_composition(item),
                    "unit": b.unit,
                    "required_quantity": 0.0,
                    "available_quantity": 0.0,
                    "shortage": 0.0,
                }
            agg[b.item_id]["required_quantity"] += required

    availability = _available_stock_for_items(db, agg)
    for item_id, row in agg.items():
        avail = availability[item_id]
        row["available_quantity"] = avail
        row["shortage"] = max(0.0, row["required_quantity"] - avail)

    return list(agg.values())


def material_requirements_for_sales_order(db: Session, sales_order_id: int) -> list[dict]:
    """For each SO line, expand BOM and compute required = qty * usage per piece.

    Returns aggregated list per item with required vs available and shortage.
    """
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        return []

    lines = db.query(SalesOrderItem).filter(SalesOrderItem.sales_order_id == sales_order_id).all()
    return _requirements_from_lines(db, lines)


def material_requirements_for_quantity(db: Session, model_id: int, items: list[dict]) -> list[dict]:
    """items: [{color, size, quantity}, ...]"""
    lines = [
        SimpleNamespace(
            model_id=model_id,
            color=line.get("color"),
            size=line.get("size"),
            quantity=line.get("quantity", 0),
        )
        for line in items
    ]
    return _requirements_from_lines(db, lines)


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
    items_by_id = _rows_by_id(db, Item, (row["item_id"] for row in material_rows))
    for row in material_rows:
        item = items_by_id.get(_int_or_none(row["item_id"]))
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
    sales_lines = list(so.items)
    models_by_id = _rows_by_id(db, Model, (line.model_id for line in sales_lines))
    for line in sales_lines:
        qty = int(line.quantity or 0)
        total_qty += qty
        model = models_by_id.get(_int_or_none(line.model_id))
        if not model:
            continue
        estimated_minutes += float(model.sam_minutes or 0) * qty

    return {
        "sales_order_id": so.id,
        "estimated_material_cost": estimated_material_cost,
        "estimated_labor_cost": 0.0,
        "estimated_electricity_cost": 0.0,
        "estimated_other_expenses": 0.0,
        "estimated_net_cost": estimated_material_cost,
        "suggested_price_15": round(estimated_material_cost * 1.15, 2),
        "suggested_price_20": round(estimated_material_cost * 1.20, 2),
        "estimated_sales_value": float(so.total_amount or 0),
        "estimated_lead_time_minutes": int(round(estimated_minutes)),
        "estimated_lead_time_hours": round(estimated_minutes / 60.0, 2),
        "total_quantity": total_qty,
        "materials": enriched_materials,
    }
