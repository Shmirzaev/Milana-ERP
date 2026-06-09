from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    CuttingRecord,
    Item,
    Model,
    ModelBOM,
    PackagingRecord,
    ProductionOrder,
    ProductionOrderItem,
    SewingRecord,
    StockBatch,
    StockMovement,
    Warehouse,
    WorkOrder,
)
from app.services.workflow import consume_item_from_batches

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
        .filter(StockMovement.item_id == item_id, StockMovement.batch_id.is_(None)) \
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
        .filter(StockMovement.item_id.in_(item_ids), StockMovement.batch_id.is_(None))
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


def _model_label_fields(db: Session, model_id: int | None) -> tuple[str | None, str | None]:
    if not model_id:
        return None, None
    model = db.get(Model, model_id)
    if not model:
        return None, None
    return model.code, model.name


def _record_work_order_ids(
    db: Session,
    model_cls,
    record_ids: set[int],
) -> dict[int, int]:
    if not record_ids:
        return {}
    rows = db.query(model_cls.id, model_cls.work_order_id).filter(model_cls.id.in_(record_ids)).all()
    return {int(record_id): int(work_order_id) for record_id, work_order_id in rows if work_order_id}


def _movement_production_order_ids(db: Session, movements: list[StockMovement]) -> dict[int, int]:
    direct_po_ids: dict[int, int] = {}
    work_order_ids: set[int] = set()
    record_ids: dict[str, set[int]] = {
        "CuttingRecord": set(),
        "SewingRecord": set(),
        "PackagingRecord": set(),
    }

    for movement in movements:
        ref_type = str(movement.reference_type or "")
        ref_id = int(movement.reference_id or 0)
        if not ref_id:
            continue
        if ref_type in {"ProductionOrder", "ProductionOrderAccessoryIssue"}:
            direct_po_ids[int(movement.id)] = ref_id
        elif ref_type == "WorkOrder":
            work_order_ids.add(ref_id)
        elif ref_type in record_ids:
            record_ids[ref_type].add(ref_id)

    record_to_work_order: dict[str, dict[int, int]] = {
        "CuttingRecord": _record_work_order_ids(db, CuttingRecord, record_ids["CuttingRecord"]),
        "SewingRecord": _record_work_order_ids(db, SewingRecord, record_ids["SewingRecord"]),
        "PackagingRecord": _record_work_order_ids(db, PackagingRecord, record_ids["PackagingRecord"]),
    }
    for mapping in record_to_work_order.values():
        work_order_ids.update(mapping.values())

    work_order_to_po: dict[int, int] = {}
    if work_order_ids:
        rows = (
            db.query(WorkOrder.id, WorkOrder.production_order_id)
            .filter(WorkOrder.id.in_(work_order_ids))
            .all()
        )
        work_order_to_po = {int(work_order_id): int(po_id) for work_order_id, po_id in rows if po_id}

    resolved: dict[int, int] = {}
    for movement in movements:
        movement_id = int(movement.id)
        if movement_id in direct_po_ids:
            resolved[movement_id] = direct_po_ids[movement_id]
            continue

        ref_type = str(movement.reference_type or "")
        ref_id = int(movement.reference_id or 0)
        work_order_id = None
        if ref_type == "WorkOrder":
            work_order_id = ref_id
        elif ref_type in record_to_work_order:
            work_order_id = record_to_work_order[ref_type].get(ref_id)
        if work_order_id and work_order_id in work_order_to_po:
            resolved[movement_id] = work_order_to_po[work_order_id]

    return resolved


def accessory_issue_summary(
    db: Session,
    *,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
) -> list[dict]:
    query = (
        db.query(StockMovement, Item)
        .join(Item, Item.id == StockMovement.item_id)
        .filter(
            Item.category.in_(ACCESSORY_CATEGORIES),
            StockMovement.movement_type.in_(("consume", "issue")),
        )
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
    )
    movements_with_items = query.all()
    movements = [movement for movement, _ in movements_with_items]
    po_ids_by_movement_id = _movement_production_order_ids(db, movements)
    if not po_ids_by_movement_id:
        return []

    all_po_ids = set(po_ids_by_movement_id.values())
    po_rows = db.query(ProductionOrder).filter(ProductionOrder.id.in_(all_po_ids)).all()
    po_by_id = {int(po.id): po for po in po_rows}

    model_ids = {int(po.model_id) for po in po_rows if po.model_id}
    models = db.query(Model).filter(Model.id.in_(model_ids)).all() if model_ids else []
    model_by_id = {int(model.id): model for model in models}

    item_by_id: dict[int, Item] = {}
    grouped: dict[tuple[int, int, str], dict] = {}
    for movement, item in movements_with_items:
        po_id = po_ids_by_movement_id.get(int(movement.id))
        if not po_id:
            continue
        po = po_by_id.get(po_id)
        if not po:
            continue
        if production_order_id is not None and int(po.id) != int(production_order_id):
            continue
        if model_id is not None and int(po.model_id) != int(model_id):
            continue

        unit = str(movement.unit or item.unit or "").strip() or item.unit
        key = (int(po.id), int(item.id), unit)
        model = model_by_id.get(int(po.model_id))
        first_at = movement.created_at
        last_at = movement.created_at
        existing = grouped.get(key)
        if not existing:
            existing = {
                "production_order_id": int(po.id),
                "production_no": po.production_no,
                "model_id": int(po.model_id),
                "model_code": model.code if model else None,
                "model_name": model.name if model else None,
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "category": item.category,
                "unit": unit,
                "issued_quantity": 0.0,
                "movement_count": 0,
                "first_issued_at": first_at,
                "last_issued_at": last_at,
            }
            grouped[key] = existing
        existing["issued_quantity"] += float(movement.quantity or 0)
        existing["movement_count"] += 1
        if first_at and (not existing["first_issued_at"] or first_at < existing["first_issued_at"]):
            existing["first_issued_at"] = first_at
        if last_at and (not existing["last_issued_at"] or last_at > existing["last_issued_at"]):
            existing["last_issued_at"] = last_at
        item_by_id[int(item.id)] = item

    rows = list(grouped.values())
    search = (q or "").strip().lower()
    if search:
        def matches(row: dict) -> bool:
            fields = [
                row.get("production_no"),
                row.get("model_code"),
                row.get("model_name"),
                row.get("item_sku"),
                row.get("item_name"),
                row.get("unit"),
            ]
            return any(search in str(value or "").lower() for value in fields)

        rows = [row for row in rows if matches(row)]

    def sort_key(row: dict) -> tuple[float, int, str]:
        dt = row.get("last_issued_at")
        timestamp = dt.timestamp() if isinstance(dt, datetime) else 0.0
        return (timestamp, int(row.get("production_order_id") or 0), str(row.get("item_sku") or ""))

    return sorted(rows, key=sort_key, reverse=True)


def accessory_issue_plan(db: Session, production_order_id: int) -> dict:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    model_code, model_name = _model_label_fields(db, po.model_id)
    po_items = (
        db.query(ProductionOrderItem)
        .filter(ProductionOrderItem.production_order_id == po.id)
        .all()
    )
    model_ids = {int(po.model_id)}
    model_ids.update(int(row.model_id) for row in po_items if row.model_id)
    bom_rows = (
        db.query(ModelBOM, Item)
        .join(Item, Item.id == ModelBOM.item_id)
        .filter(ModelBOM.model_id.in_(model_ids), Item.category.in_(ACCESSORY_CATEGORIES))
        .all()
    )

    by_model: dict[int, list[tuple[ModelBOM, Item]]] = {}
    for bom, item in bom_rows:
        by_model.setdefault(int(bom.model_id), []).append((bom, item))

    required: dict[tuple[int, str], dict] = {}

    def add_requirement(bom: ModelBOM, item: Item, planned_qty: int) -> None:
        qty = float(bom.quantity_per_piece or 0) * max(0, int(planned_qty or 0))
        qty *= 1.0 + float(bom.waste_percent or 0) / 100.0
        if qty <= 0:
            return
        unit = str(bom.unit or item.unit or "").strip() or item.unit
        key = (int(item.id), unit)
        row = required.get(key)
        if not row:
            row = {
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "category": item.category,
                "unit": unit,
                "required_quantity": 0.0,
            }
            required[key] = row
        row["required_quantity"] += qty

    if po_items:
        for line in po_items:
            for bom, item in by_model.get(int(line.model_id or po.model_id), []):
                if bom.size and bom.size != line.size:
                    continue
                if bom.color and bom.color != line.color:
                    continue
                add_requirement(bom, item, int(line.planned_quantity or 0))
    else:
        for bom, item in by_model.get(int(po.model_id), []):
            add_requirement(bom, item, int(po.planned_quantity or 0))

    issued_rows = accessory_issue_summary(db, production_order_id=po.id)
    issued_by_item_unit = {
        (int(row["item_id"]), str(row["unit"])): float(row["issued_quantity"] or 0)
        for row in issued_rows
    }

    rows = []
    for key, row in required.items():
        issued = issued_by_item_unit.get(key, 0.0)
        available = current_stock_for_item(db, int(row["item_id"]))
        remaining = max(0.0, float(row["required_quantity"] or 0) - issued)
        rows.append({
            **row,
            "issued_quantity": issued,
            "remaining_quantity": remaining,
            "available_quantity": available,
            "shortage": max(0.0, remaining - available),
        })

    rows.sort(key=lambda row: (row["category"], row["item_sku"]))
    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "model_id": int(po.model_id),
        "model_code": model_code,
        "model_name": model_name,
        "planned_quantity": int(po.planned_quantity or 0),
        "rows": rows,
    }


def issue_accessories_to_production_order(
    db: Session,
    *,
    production_order_id: int,
    lines: list[dict],
    user_id: int | None,
) -> dict:
    plan = accessory_issue_plan(db, production_order_id)
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    plan_by_item_id = {int(row["item_id"]): row for row in plan["rows"]}
    issued = []
    for raw in lines:
        item_id = int(raw.get("item_id") or 0)
        quantity = float(raw.get("quantity") or 0)
        if quantity <= 0:
            continue

        plan_row = plan_by_item_id.get(item_id)
        if not plan_row:
            raise HTTPException(400, f"Item #{item_id} is not an accessory BOM item for this production order")

        remaining = float(plan_row.get("remaining_quantity") or 0)
        if quantity > remaining + 1e-9:
            raise HTTPException(
                409,
                f"Issue quantity for {plan_row['item_sku']} exceeds remaining accessory requirement",
            )

        item = db.get(Item, item_id)
        if not item or item.category not in ACCESSORY_CATEGORIES:
            raise HTTPException(400, f"Item #{item_id} is not an accessory item")

        unit = str(raw.get("unit") or plan_row.get("unit") or item.unit or "").strip() or item.unit
        consumed = consume_item_from_batches(
            db,
            item_id=item.id,
            quantity=quantity,
            unit=unit,
            reference_type="ProductionOrder",
            reference_id=po.id,
            user_id=user_id,
            require_available=True,
        )
        issued.append({
            "item_id": int(item.id),
            "item_sku": item.sku,
            "item_name": item.name,
            "quantity": consumed,
            "unit": unit,
        })

    if not issued:
        raise HTTPException(400, "No accessory issue quantities provided")

    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "issued": issued,
    }
