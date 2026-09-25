from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import String, and_, case, func, literal, or_, text, union_all
from sqlalchemy.orm import Session, joinedload, lazyload, load_only, noload

from app.core.pagination import clamp_pagination
from app.core.model_search import model_code_contains, normalized_model_code_column, normalized_model_code_key
from app.models import (
    CuttingRecord,
    Item,
    ManualAccessoryIssue,
    MaterialReservation,
    Model,
    ModelBOM,
    PackagingRecord,
    PrintingRecord,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    SalesOrder,
    SewingRecord,
    StockBatch,
    StockMovement,
    SystemSetting,
    Warehouse,
    WorkOrder,
    public_production_order_no,
)
from app.services.numbering import next_material_reservation_nos
from app.services.workflow import (
    STOCK_ITEM_AVAILABILITY_LOCK_NAMESPACE,
    consume_item_from_batches,
    consume_stock_batch,
    notify_department,
)

MATERIAL_CATEGORIES = ("fabric", "semi_finished")
ACCESSORY_CATEGORIES = ("accessory", "packaging")
RESERVABLE_CATEGORIES = MATERIAL_CATEGORIES + ACCESSORY_CATEGORIES
# Canonical item kinds documented by Item.category. Keep waste and finished
# goods writable even though they are not part of the reservation UI groups.
ITEM_CATEGORIES = RESERVABLE_CATEGORIES + ("finished", "waste")
ACTIVE_RESERVATION_STATUSES = ("reserved", "partially_consumed")
RESERVATION_STATUSES = ("reserved", "partially_consumed", "consumed", "released", "cancelled")
RESERVATION_TYPES = ("material", "accessory", "packaging")
RESERVATION_SOURCES = ("manual", "auto_bom", "planning")
REQUIRE_RESERVATION_SETTING = "require_material_reservation_before_cutting"
ACCESSORY_SEWING_BLOCK_REASON = "Accessories must be issued before sewing."
EPSILON = 1e-9
_ACCESSORY_QUANTITY_QUANTUM = Decimal("0.0001")
_RESERVATION_LOCK_NAMESPACE = STOCK_ITEM_AVAILABILITY_LOCK_NAMESPACE
_ACCESSORY_RETURN_LOCK_NAMESPACE = 1_297_047_634


def _accessory_match_key(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


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
    """Return current batch balances plus the applicable batchless ledger changes."""
    bq = db.query(func.coalesce(func.sum(StockBatch.quantity), 0)).filter(StockBatch.item_id == item_id)
    if warehouse_id is not None:
        bq = bq.filter(StockBatch.warehouse_id == warehouse_id)
    batch_total = float(bq.scalar() or 0)

    out_types = ("issue", "consume", "waste", "shipment")
    in_types = ("produce", "return", "adjustment")
    outgoing = StockMovement.movement_type.in_(out_types)
    incoming = StockMovement.movement_type.in_(in_types)
    if warehouse_id is not None:
        # Transfers change each endpoint but have no effect on the global total.
        # Legacy movements with no location belong only to the global balance.
        outgoing = and_(
            StockMovement.movement_type.in_((*out_types, "transfer")),
            StockMovement.from_warehouse_id == warehouse_id,
        )
        incoming = and_(
            StockMovement.movement_type.in_((*in_types, "transfer")),
            StockMovement.to_warehouse_id == warehouse_id,
        )
    # Batch-linked movements are already reflected in StockBatch.quantity.
    incoming_total, outgoing_total = db.query(
        func.coalesce(func.sum(case((incoming, StockMovement.quantity), else_=0)), 0),
        func.coalesce(func.sum(case((outgoing, StockMovement.quantity), else_=0)), 0),
    ).filter(StockMovement.item_id == item_id, StockMovement.batch_id.is_(None)).one()
    return batch_total + float(incoming_total) - float(outgoing_total)


def _open_reservation_quantity(reservation: MaterialReservation) -> float:
    return max(
        0.0,
        float(reservation.reserved_quantity or 0)
        - float(reservation.consumed_quantity or 0)
        - float(reservation.released_quantity or 0),
    )


def _covered_reservation_quantity(reservation: MaterialReservation) -> float:
    if reservation.status == "cancelled":
        return 0.0
    consumed = max(0.0, float(reservation.consumed_quantity or 0))
    active_remaining = _open_reservation_quantity(reservation) if reservation.status in ACTIVE_RESERVATION_STATUSES else 0.0
    return consumed + active_remaining


def _reservation_type_for_category(category: str | None) -> str:
    normalized = str(category or "").strip().lower()
    if normalized == "packaging":
        return "packaging"
    if normalized == "accessory":
        return "accessory"
    return "material"


def _active_reserved_sum_query(db: Session):
    return func.coalesce(
        func.sum(
            MaterialReservation.reserved_quantity
            - MaterialReservation.consumed_quantity
            - MaterialReservation.released_quantity
        ),
        0,
    )


def reserved_stock_for_item(db: Session, item_id: int, warehouse_id: int | None = None) -> float:
    qry = db.query(_active_reserved_sum_query(db)).filter(
        MaterialReservation.item_id == item_id,
        MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
    )
    if warehouse_id is not None:
        qry = qry.filter(MaterialReservation.warehouse_id == warehouse_id)
    return max(0.0, float(qry.scalar() or 0))


def available_stock_for_item(db: Session, item_id: int, warehouse_id: int | None = None) -> float:
    return current_stock_for_item(db, item_id, warehouse_id=warehouse_id) - reserved_stock_for_item(
        db,
        item_id,
        warehouse_id=warehouse_id,
    )


_BULK_STOCK_CHUNK_SIZE = 400


def available_stock_for_items(db: Session, item_ids) -> dict[int | None, float]:
    """Bulk global equivalent of available_stock_for_item for planning reads."""
    raw_ids = set(item_ids)
    ids = sorted({int(item_id) for item_id in raw_ids if item_id is not None})
    result = {item_id: 0.0 for item_id in ids}
    if None in raw_ids:
        result[None] = 0.0
    out_types = ("issue", "consume", "waste", "shipment")
    in_types = ("produce", "return", "adjustment")
    for start in range(0, len(ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        batch_totals = dict(
            db.query(StockBatch.item_id, func.coalesce(func.sum(StockBatch.quantity), 0))
            .filter(StockBatch.item_id.in_(chunk)).group_by(StockBatch.item_id).all()
        )
        movement_totals = {
            int(item_id): (float(incoming or 0), float(outgoing or 0))
            for item_id, incoming, outgoing in db.query(
                StockMovement.item_id,
                func.coalesce(func.sum(case((StockMovement.movement_type.in_(in_types), StockMovement.quantity), else_=0)), 0),
                func.coalesce(func.sum(case((StockMovement.movement_type.in_(out_types), StockMovement.quantity), else_=0)), 0),
            ).filter(
                StockMovement.item_id.in_(chunk), StockMovement.batch_id.is_(None),
            ).group_by(StockMovement.item_id).all()
        }
        reserved_totals = dict(
            db.query(MaterialReservation.item_id, _active_reserved_sum_query(db))
            .filter(
                MaterialReservation.item_id.in_(chunk),
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            ).group_by(MaterialReservation.item_id).all()
        )
        for item_id in chunk:
            incoming, outgoing = movement_totals.get(item_id, (0.0, 0.0))
            reserved = max(0.0, float(reserved_totals.get(item_id, 0) or 0))
            result[item_id] = float(batch_totals.get(item_id, 0) or 0) + incoming - outgoing - reserved
    return result


def current_stock_for_batch(db: Session, stock_batch_id: int) -> float:
    quantity = db.query(StockBatch.quantity).filter(StockBatch.id == stock_batch_id).scalar()
    if quantity is None:
        raise HTTPException(404, "Stock batch not found")
    return float(quantity or 0)


def reserved_stock_for_batch(db: Session, stock_batch_id: int) -> float:
    return max(
        0.0,
        float(
            db.query(_active_reserved_sum_query(db))
            .filter(
                MaterialReservation.stock_batch_id == stock_batch_id,
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
            .scalar()
            or 0
        ),
    )


def available_stock_for_batch(db: Session, stock_batch_id: int) -> float:
    return current_stock_for_batch(db, stock_batch_id) - reserved_stock_for_batch(db, stock_batch_id)


def _bom_requirement_rows(
    db: Session,
    po: ProductionOrder,
    categories: tuple[str, ...] | None = None,
) -> list[dict]:
    po_items = (
        db.query(
            ProductionOrderItem.model_id,
            ProductionOrderItem.planned_quantity,
            ProductionOrderItem.size,
            ProductionOrderItem.color,
        )
        .filter(ProductionOrderItem.production_order_id == po.id)
        .all()
    )
    model_ids = {int(po.model_id)}
    model_ids.update(int(row.model_id) for row in po_items if row.model_id)
    qry = (
        db.query(ModelBOM, Item)
        .join(Item, Item.id == ModelBOM.item_id)
        .filter(ModelBOM.model_id.in_(model_ids))
    )
    if categories:
        qry = qry.filter(Item.category.in_(categories))
    bom_rows = qry.all()

    by_model: dict[int, list[tuple[ModelBOM, Item]]] = {}
    for bom, item in bom_rows:
        by_model.setdefault(int(bom.model_id), []).append((bom, item))

    required: dict[tuple[int, str, int | None], dict] = {}
    explicit_materials = (
        db.query(ProductionOrderMaterial)
        .filter(ProductionOrderMaterial.production_order_id == po.id)
        .order_by(ProductionOrderMaterial.position.asc())
        .all()
    )
    include_materials = categories is None or any(category in MATERIAL_CATEGORIES for category in categories)
    if explicit_materials and include_materials:
        planned_batch_ids = sorted({int(row.stock_batch_id) for row in explicit_materials})
        planned_batches: dict[int, tuple[StockBatch, Item]] = {}
        for start in range(0, len(planned_batch_ids), _BULK_STOCK_CHUNK_SIZE):
            chunk = planned_batch_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
            rows = (
                db.query(StockBatch, Item)
                .options(lazyload(StockBatch.item))
                .join(Item, Item.id == StockBatch.item_id)
                .filter(StockBatch.id.in_(chunk))
                .all()
            )
            planned_batches.update((int(batch.id), (batch, item)) for batch, item in rows)
        for planned in explicit_materials:
            planned_batch = planned_batches.get(int(planned.stock_batch_id))
            if not planned_batch:
                continue
            stock_batch, item = planned_batch
            unit = str(planned.unit or stock_batch.unit or item.unit or "").strip() or item.unit
            key = (int(item.id), unit, int(stock_batch.id))
            required[key] = {
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "item_image_url": item.image_url,
                "composition": _item_composition(item),
                "category": item.category,
                "reservation_type": _reservation_type_for_category(item.category),
                "unit": unit,
                "stock_batch_id": int(stock_batch.id),
                "stock_batch_no": stock_batch.batch_no,
                "stock_batch_image_url": stock_batch.image_url,
                "stock_batch_color": stock_batch.color,
                "required_quantity": float(planned.estimated_quantity or 0),
            }

    planned_fabric_batch = (
        db.get(StockBatch, po.fabric_batch_id)
        if po.fabric_batch_id and not explicit_materials
        else None
    )

    def add_requirement(bom: ModelBOM, item: Item, planned_qty: int) -> None:
        if explicit_materials and str(item.category or "").lower() in MATERIAL_CATEGORIES:
            return
        qty = float(bom.quantity_per_piece or 0) * max(0, int(planned_qty or 0))
        qty *= 1.0 + float(bom.waste_percent or 0) / 100.0
        if qty <= 0:
            return
        unit = str(bom.unit or item.unit or "").strip() or item.unit
        stock_batch = getattr(bom, "stock_batch", None)
        stock_batch_id = int(bom.stock_batch_id) if bom.stock_batch_id else None
        if (
            planned_fabric_batch
            and str(item.category or "").lower() in {"fabric", "semi_finished"}
            and int(planned_fabric_batch.item_id) == int(item.id)
        ):
            stock_batch = planned_fabric_batch
            stock_batch_id = int(planned_fabric_batch.id)
        key = (int(item.id), unit, stock_batch_id)
        row = required.get(key)
        if not row:
            row = {
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "item_image_url": item.image_url,
                "composition": _item_composition(item),
                "category": item.category,
                "reservation_type": _reservation_type_for_category(item.category),
                "unit": unit,
                "stock_batch_id": stock_batch_id,
                "stock_batch_no": stock_batch.batch_no if stock_batch else None,
                "stock_batch_image_url": stock_batch.image_url if stock_batch else None,
                "stock_batch_color": stock_batch.color if stock_batch else None,
                "required_quantity": 0.0,
            }
            required[key] = row
        row["required_quantity"] += qty

    if po_items:
        for model_id, planned_quantity, size, color in po_items:
            for bom, item in by_model.get(int(model_id or po.model_id), []):
                if bom.size and bom.size != size:
                    continue
                if bom.color and bom.color != color:
                    continue
                add_requirement(bom, item, int(planned_quantity or 0))
    else:
        for bom, item in by_model.get(int(po.model_id), []):
            add_requirement(bom, item, int(po.planned_quantity or 0))

    rows = list(required.values())
    rows.sort(key=lambda row: (row["category"], row["item_sku"], row["unit"]))
    return rows


def _suggest_batches_for_requirement(
    db: Session,
    *,
    item_id: int,
    unit: str,
    quantity: float,
    stock_batch_id: int | None = None,
) -> list[dict]:
    left = max(0.0, float(quantity or 0))
    if left <= EPSILON:
        return []
    qry = db.query(StockBatch).filter(StockBatch.item_id == item_id, StockBatch.quantity > 0)
    if stock_batch_id is not None:
        qry = qry.filter(StockBatch.id == stock_batch_id)
    batches = qry.order_by(StockBatch.received_date.asc(), StockBatch.id.asc()).all()
    out: list[dict] = []
    for batch in batches:
        if left <= EPSILON:
            break
        if str(batch.unit or "").strip() != str(unit or "").strip():
            continue
        reserved = reserved_stock_for_batch(db, int(batch.id))
        available = max(0.0, float(batch.quantity or 0) - reserved)
        if available <= EPSILON:
            continue
        suggested = min(left, available)
        out.append({
            "stock_batch_id": int(batch.id),
            "batch_no": batch.batch_no,
            "warehouse_id": int(batch.warehouse_id),
            "received_date": batch.received_date,
            "current_quantity": float(batch.quantity or 0),
            "reserved_quantity": reserved,
            "available_quantity": available,
            "suggested_quantity": suggested,
            "unit": batch.unit,
        })
        left -= suggested
    return out


def _reservation_coverage_by_item_unit(db: Session, production_order_id: int) -> dict[tuple[int, str], float]:
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id == production_order_id)
        .all()
    )
    coverage: dict[tuple[int, str], float] = {}
    for reservation in reservations:
        key = (int(reservation.item_id), str(reservation.unit or ""))
        coverage[key] = coverage.get(key, 0.0) + _covered_reservation_quantity(reservation)
    return coverage


def _reservation_coverage_by_item_unit_batch(db: Session, production_order_id: int) -> dict[tuple[int, str, int], float]:
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id == production_order_id)
        .filter(MaterialReservation.stock_batch_id.isnot(None))
        .all()
    )
    coverage: dict[tuple[int, str, int], float] = {}
    for reservation in reservations:
        key = (int(reservation.item_id), str(reservation.unit or ""), int(reservation.stock_batch_id))
        coverage[key] = coverage.get(key, 0.0) + _covered_reservation_quantity(reservation)
    return coverage


def _reservation_coverage_maps(
    db: Session,
    production_order_id: int,
) -> tuple[dict[tuple[int, str], float], dict[tuple[int, str, int], float]]:
    rows = (
        db.query(
            MaterialReservation.item_id,
            MaterialReservation.unit,
            MaterialReservation.stock_batch_id,
            MaterialReservation.reserved_quantity,
            MaterialReservation.consumed_quantity,
            MaterialReservation.released_quantity,
            MaterialReservation.status,
        )
        .filter(MaterialReservation.production_order_id == production_order_id)
        .all()
    )
    by_item: dict[tuple[int, str], float] = {}
    by_batch: dict[tuple[int, str, int], float] = {}
    for item_id, unit, batch_id, reserved, consumed, released, status in rows:
        raw_consumed_quantity = float(consumed or 0)
        consumed_quantity = max(0.0, raw_consumed_quantity)
        active_remaining = (
            max(0.0, float(reserved or 0) - raw_consumed_quantity - float(released or 0))
            if status in ACTIVE_RESERVATION_STATUSES
            else 0.0
        )
        covered = 0.0 if status == "cancelled" else consumed_quantity + active_remaining
        item_key = (int(item_id), str(unit or ""))
        by_item[item_key] = by_item.get(item_key, 0.0) + covered
        if batch_id is not None:
            batch_key = (*item_key, int(batch_id))
            by_batch[batch_key] = by_batch.get(batch_key, 0.0) + covered
    return by_item, by_batch


def _reservation_plan_stock_context(db: Session, requirement_rows: list[dict]) -> dict:
    item_ids = sorted({int(row["item_id"]) for row in requirement_rows})
    exact_batch_ids = sorted({
        int(row["stock_batch_id"])
        for row in requirement_rows
        if row.get("stock_batch_id") is not None
    })
    batch_totals: dict[int, float] = {}
    movement_totals: dict[int, tuple[float, float]] = {}
    reserved_by_item_raw: dict[int, float] = {}
    reserved_by_batch_raw: dict[int, float] = {}
    candidate_batches_by_item: dict[int, dict[int, StockBatch]] = {}
    batches_by_id: dict[int, StockBatch] = {}
    in_types = ("produce", "return", "adjustment")
    out_types = ("issue", "consume", "waste", "shipment")

    for start in range(0, len(item_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = item_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        batch_totals.update({
            int(item_id): float(quantity or 0)
            for item_id, quantity in (
                db.query(StockBatch.item_id, func.coalesce(func.sum(StockBatch.quantity), 0))
                .filter(StockBatch.item_id.in_(chunk))
                .group_by(StockBatch.item_id)
                .all()
            )
        })
        movement_totals.update({
            int(item_id): (float(incoming or 0), float(outgoing or 0))
            for item_id, incoming, outgoing in (
                db.query(
                    StockMovement.item_id,
                    func.coalesce(func.sum(case((StockMovement.movement_type.in_(in_types), StockMovement.quantity), else_=0)), 0),
                    func.coalesce(func.sum(case((StockMovement.movement_type.in_(out_types), StockMovement.quantity), else_=0)), 0),
                )
                .filter(StockMovement.item_id.in_(chunk), StockMovement.batch_id.is_(None))
                .group_by(StockMovement.item_id)
                .all()
            )
        })
        for item_id, quantity in (
            db.query(
                MaterialReservation.item_id,
                _active_reserved_sum_query(db),
            )
            .filter(
                MaterialReservation.item_id.in_(chunk),
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
            .group_by(MaterialReservation.item_id)
            .all()
        ):
            reserved_by_item_raw[int(item_id)] = reserved_by_item_raw.get(int(item_id), 0.0) + float(quantity or 0)
        candidates = (
            db.query(StockBatch)
            .options(lazyload(StockBatch.item))
            .filter(StockBatch.item_id.in_(chunk), StockBatch.quantity > 0)
            .order_by(StockBatch.item_id, StockBatch.received_date, StockBatch.id)
            .all()
        )
        for batch in candidates:
            batch_id = int(batch.id)
            item_id = int(batch.item_id)
            batches_by_id[batch_id] = batch
            candidate_batches_by_item.setdefault(item_id, {})[batch_id] = batch

    for start in range(0, len(exact_batch_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = exact_batch_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        exact_batches = (
            db.query(StockBatch)
            .options(lazyload(StockBatch.item))
            .filter(StockBatch.id.in_(chunk))
            .all()
        )
        batches_by_id.update((int(batch.id), batch) for batch in exact_batches)

    candidate_batch_ids = sorted(batches_by_id)
    for start in range(0, len(candidate_batch_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = candidate_batch_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        reserved_by_batch_raw.update({
            int(batch_id): float(quantity or 0)
            for batch_id, quantity in (
                db.query(
                    MaterialReservation.stock_batch_id,
                    _active_reserved_sum_query(db),
                )
                .filter(
                    MaterialReservation.stock_batch_id.in_(chunk),
                    MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
                )
                .group_by(MaterialReservation.stock_batch_id)
                .all()
            )
        })

    current_by_item: dict[int, float] = {}
    reserved_by_item: dict[int, float] = {}
    for item_id in item_ids:
        incoming, outgoing = movement_totals.get(item_id, (0.0, 0.0))
        current_by_item[item_id] = float(batch_totals.get(item_id, 0.0)) + incoming - outgoing
        reserved_by_item[item_id] = max(0.0, reserved_by_item_raw.get(item_id, 0.0))
    return {
        "current_by_item": current_by_item,
        "reserved_by_item": reserved_by_item,
        "reserved_by_batch": {
            batch_id: max(0.0, quantity)
            for batch_id, quantity in reserved_by_batch_raw.items()
        },
        "candidate_batches_by_item": {
            item_id: list(batches.values())
            for item_id, batches in candidate_batches_by_item.items()
        },
        "batches_by_id": batches_by_id,
    }


def reservation_plan_for_production_order(db: Session, production_order_id: int, categories: tuple[str, ...] | None = None) -> dict:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    model_code, model_name = _model_label_fields(db, po.model_id)
    coverage, batch_coverage = _reservation_coverage_maps(db, int(po.id))
    requirement_rows = _bom_requirement_rows(db, po, categories or RESERVABLE_CATEGORIES)
    stock_context = _reservation_plan_stock_context(db, requirement_rows)
    rows = []
    for row in requirement_rows:
        item_id = int(row["item_id"])
        unit = str(row["unit"])
        stock_batch_id = int(row["stock_batch_id"]) if row.get("stock_batch_id") else None
        if stock_batch_id is not None:
            coverage_key = (item_id, unit, stock_batch_id)
            already_reserved = float(batch_coverage.get(coverage_key, 0.0))
        else:
            coverage_key = (item_id, unit)
            already_reserved = float(coverage.get(coverage_key, 0.0))
        required = float(row["required_quantity"] or 0)
        remaining = max(0.0, required - already_reserved)
        if stock_batch_id is not None:
            batch = stock_context["batches_by_id"].get(stock_batch_id)
            if not batch:
                raise HTTPException(404, "Stock batch not found")
            current = float(batch.quantity or 0)
            reserved = float(stock_context["reserved_by_batch"].get(stock_batch_id, 0.0))
        else:
            current = float(stock_context["current_by_item"].get(item_id, 0.0))
            reserved = float(stock_context["reserved_by_item"].get(item_id, 0.0))
        available = current - reserved
        shortage = max(0.0, remaining - max(0.0, available))
        left = remaining
        suggested_batches = []
        if stock_batch_id is not None:
            exact_candidate = stock_context["batches_by_id"].get(stock_batch_id)
            candidates = [exact_candidate] if exact_candidate and float(exact_candidate.quantity or 0) > 0 else []
        else:
            candidates = stock_context["candidate_batches_by_item"].get(item_id, [])
        for candidate in candidates:
            if left <= EPSILON:
                break
            candidate_id = int(candidate.id)
            if str(candidate.unit or "").strip() != unit.strip():
                continue
            candidate_reserved = float(stock_context["reserved_by_batch"].get(candidate_id, 0.0))
            candidate_available = max(0.0, float(candidate.quantity or 0) - candidate_reserved)
            if candidate_available <= EPSILON:
                continue
            suggested = min(left, candidate_available)
            suggested_batches.append({
                "stock_batch_id": candidate_id,
                "batch_no": candidate.batch_no,
                "warehouse_id": int(candidate.warehouse_id),
                "received_date": candidate.received_date,
                "current_quantity": float(candidate.quantity or 0),
                "reserved_quantity": candidate_reserved,
                "available_quantity": candidate_available,
                "suggested_quantity": suggested,
                "unit": candidate.unit,
            })
            left -= suggested
        if remaining <= EPSILON:
            status = "ready"
        elif shortage > EPSILON:
            status = "shortage"
        else:
            status = "partial"
        rows.append({
            **row,
            "required_quantity": required,
            "already_reserved_quantity": already_reserved,
            "remaining_to_reserve": remaining,
            "current_stock": current,
            "reserved_stock": reserved,
            "available_stock": available,
            "shortage": shortage,
            "suggested_batches": suggested_batches,
            "status": status,
        })

    total_required = sum(float(row["required_quantity"] or 0) for row in rows)
    total_reserved = sum(float(row["already_reserved_quantity"] or 0) for row in rows)
    total_remaining = sum(float(row["remaining_to_reserve"] or 0) for row in rows)
    total_shortage = sum(float(row["shortage"] or 0) for row in rows)
    if not rows:
        readiness_status = "no_bom"
    elif total_remaining <= EPSILON:
        readiness_status = "ready"
    elif total_shortage > EPSILON:
        readiness_status = "shortage"
    else:
        readiness_status = "partial"

    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "sales_order_id": int(po.sales_order_id) if po.sales_order_id else None,
        "model_id": int(po.model_id),
        "model_code": model_code,
        "model_name": model_name,
        "planned_quantity": int(po.planned_quantity or 0),
        "status": readiness_status,
        "is_complete": total_remaining <= EPSILON,
        "warning": None if total_remaining <= EPSILON else "Material reservation is incomplete before cutting.",
        "summary": {
            "required_quantity": total_required,
            "already_reserved_quantity": total_reserved,
            "remaining_to_reserve": total_remaining,
            "shortage": total_shortage,
            "line_count": len(rows),
            "ready_line_count": sum(1 for row in rows if row["status"] == "ready"),
            "shortage_line_count": sum(1 for row in rows if row["status"] == "shortage"),
        },
        "rows": rows,
    }


def _lock_reservation_resources(db: Session, lines: list[dict]) -> dict[int, StockBatch]:
    # Preserve pending stock changes before refreshing any already-loaded batch.
    db.flush()
    batches: dict[int, StockBatch] = {}
    batch_ids = sorted({int(line["stock_batch_id"]) for line in lines if line.get("stock_batch_id")})
    if batch_ids:
        qry = db.query(StockBatch).filter(StockBatch.id.in_(batch_ids)).populate_existing()
        if db.bind and db.bind.dialect.name == "postgresql":
            qry = qry.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
        batches = {int(batch.id): batch for batch in qry.order_by(StockBatch.id).all()}

    if db.bind and db.bind.dialect.name == "postgresql":
        # Cutting callers may already hold batch locks, so always acquire those
        # before reservation item locks. Acquire every resource before checking
        # availability or entering the reservation-number stream, even when the
        # request lists several items/batches in a different order.
        # Use one item key across warehouses and batched/unbatched reservations:
        # an unbatched availability check includes reservations for its batches.
        item_ids = sorted({int(line.get("item_id") or 0) for line in lines})
        db.execute(
            text(
                "SELECT pg_advisory_xact_lock(:namespace, lock_id) "
                "FROM unnest(CAST(:item_ids AS INTEGER[])) AS ordered_locks(lock_id) "
                "ORDER BY lock_id"
            ),
            {"namespace": _RESERVATION_LOCK_NAMESPACE, "item_ids": item_ids},
        )
    return batches


def _reservation_read_context(
    db: Session,
    lines: list[dict],
    locked_batches: dict[int, StockBatch],
    *,
    preloaded_items: dict[int, Item] | None = None,
) -> tuple[dict[int, Item], dict[int, Warehouse], dict[int, float], dict[tuple[int, int | None], float]]:
    """Read reservation references and availability once for the whole request.

    The caller still validates lines in input order, but the immutable item,
    warehouse, batch-balance and reservation reads are set based.  This keeps
    the lock order established by ``_lock_reservation_resources`` intact while
    avoiding a query per cutting-passport material line.
    """
    item_ids = sorted({int(line.get("item_id") or 0) for line in lines})
    if preloaded_items is None:
        items = {
            int(row.id): row
            for row in db.query(Item).filter(Item.id.in_(item_ids)).all()
        }
    else:
        items = {
            item_id: preloaded_items[item_id]
            for item_id in item_ids
            if item_id in preloaded_items
        }
    warehouse_ids = sorted({
        int(line["warehouse_id"])
        for line in lines
        if line.get("warehouse_id") and not line.get("stock_batch_id")
    })
    warehouses = {
        int(row.id): row
        for row in (db.query(Warehouse).filter(Warehouse.id.in_(warehouse_ids)).all() if warehouse_ids else [])
    }

    # Batch reservations are included separately because a batch-bound line
    # must not borrow the item's unbatched balance.
    batch_ids = sorted(locked_batches)
    batch_reserved: dict[int, float] = {}
    if batch_ids:
        batch_reserved = {
            int(batch_id): max(0.0, float(quantity or 0))
            for batch_id, quantity in db.query(
                MaterialReservation.stock_batch_id,
                _active_reserved_sum_query(db),
            ).filter(
                MaterialReservation.stock_batch_id.in_(batch_ids),
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            ).group_by(MaterialReservation.stock_batch_id).all()
        }

    # The unbatched stock calculation mirrors current_stock_for_item,
    # including transfer direction for warehouse-scoped requests.
    stock_by_key: dict[tuple[int, int | None], float] = {}
    batch_totals = db.query(
        StockBatch.item_id, StockBatch.warehouse_id, func.coalesce(func.sum(StockBatch.quantity), 0),
    ).filter(StockBatch.item_id.in_(item_ids)).group_by(
        StockBatch.item_id, StockBatch.warehouse_id,
    ).all()
    for item_id, warehouse_id, quantity in batch_totals:
        stock_by_key[(int(item_id), int(warehouse_id))] = float(quantity or 0)

    movement_rows = db.query(
        StockMovement.item_id,
        StockMovement.movement_type,
        func.coalesce(func.sum(StockMovement.quantity), 0),
        StockMovement.from_warehouse_id,
        StockMovement.to_warehouse_id,
    ).filter(
        StockMovement.item_id.in_(item_ids),
        StockMovement.batch_id.is_(None),
    ).group_by(
        StockMovement.item_id,
        StockMovement.movement_type,
        StockMovement.from_warehouse_id,
        StockMovement.to_warehouse_id,
    ).all()
    global_movement: dict[int, float] = {}
    warehouse_movement: dict[tuple[int, int], float] = {}
    out_types = {"issue", "consume", "waste", "shipment"}
    in_types = {"produce", "return", "adjustment"}
    for item_id, movement_type, quantity, from_warehouse_id, to_warehouse_id in movement_rows:
        item_id = int(item_id)
        amount = float(quantity or 0)
        signed = amount if movement_type in in_types else -amount if movement_type in out_types else 0.0
        global_movement[item_id] = global_movement.get(item_id, 0.0) + signed
        if movement_type == "transfer":
            if from_warehouse_id is not None:
                key = (item_id, int(from_warehouse_id))
                warehouse_movement[key] = warehouse_movement.get(key, 0.0) - amount
            if to_warehouse_id is not None:
                key = (item_id, int(to_warehouse_id))
                warehouse_movement[key] = warehouse_movement.get(key, 0.0) + amount
        elif from_warehouse_id is not None or to_warehouse_id is not None:
            warehouse_id = to_warehouse_id if movement_type in in_types else from_warehouse_id
            if warehouse_id is not None:
                key = (item_id, int(warehouse_id))
                warehouse_movement[key] = warehouse_movement.get(key, 0.0) + signed

    reservation_rows = db.query(
        MaterialReservation.item_id,
        MaterialReservation.warehouse_id,
        _active_reserved_sum_query(db),
    ).filter(
        MaterialReservation.item_id.in_(item_ids),
        MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
    ).group_by(MaterialReservation.item_id, MaterialReservation.warehouse_id).all()
    reserved_by_key: dict[tuple[int, int | None], float] = {}
    for item_id, warehouse_id, quantity in reservation_rows:
        key = (int(item_id), int(warehouse_id) if warehouse_id is not None else None)
        reserved_by_key[key] = reserved_by_key.get(key, 0.0) + max(0.0, float(quantity or 0))

    available_by_key: dict[tuple[int, int | None], float] = {}
    global_stock = {
        item_id: sum(quantity for (stock_item, _), quantity in stock_by_key.items() if stock_item == item_id)
        for item_id in item_ids
    }
    global_reserved = {
        item_id: sum(quantity for (reserved_item, _), quantity in reserved_by_key.items() if reserved_item == item_id)
        for item_id in item_ids
    }
    for item_id in item_ids:
        available_by_key[(item_id, None)] = (
            global_stock[item_id] + global_movement.get(item_id, 0.0) - global_reserved[item_id]
        )
        for warehouse_id in warehouse_ids:
            key = (item_id, warehouse_id)
            available_by_key[key] = (
                stock_by_key.get(key, 0.0)
                + warehouse_movement.get(key, 0.0)
                - reserved_by_key.get(key, 0.0)
            )
    return items, warehouses, batch_reserved, available_by_key


def create_material_reservations(
    db: Session,
    *,
    production_order_id: int,
    lines: list[dict],
    user_id: int | None,
    source: str = "manual",
    preloaded_items: dict[int, Item] | None = None,
) -> list[MaterialReservation]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    if source not in RESERVATION_SOURCES:
        raise HTTPException(400, "Invalid reservation source")
    if not lines:
        raise HTTPException(400, "No reservation lines provided")

    locked_batches = _lock_reservation_resources(db, lines)
    items, warehouses, batch_reserved, available_by_key = _reservation_read_context(
        db,
        lines,
        locked_batches,
        preloaded_items=preloaded_items,
    )
    used_by_key: dict[tuple[str, int, int | None], float] = {}
    reservation_values: list[dict] = []
    for idx, raw in enumerate(lines, start=1):
        item_id = int(raw.get("item_id") or 0)
        quantity = float(raw.get("reserved_quantity") or raw.get("quantity") or 0)
        unit = str(raw.get("unit") or "").strip()
        stock_batch_id = int(raw["stock_batch_id"]) if raw.get("stock_batch_id") else None
        warehouse_id = int(raw["warehouse_id"]) if raw.get("warehouse_id") else None
        notes = str(raw.get("notes") or "").strip() or None
        if quantity <= 0:
            raise HTTPException(400, f"Reservation line #{idx} quantity must be greater than zero")
        item = items.get(item_id)
        if not item:
            raise HTTPException(404, f"Item #{item_id} not found")
        if item.category not in RESERVABLE_CATEGORIES:
            raise HTTPException(400, f"Item {item.sku} is not a reservable material/accessory item")
        item_unit = str(item.unit or "").strip()
        unit = unit or item_unit
        reservation_type = str(raw.get("reservation_type") or _reservation_type_for_category(item.category)).strip()
        if reservation_type not in RESERVATION_TYPES:
            raise HTTPException(400, "Invalid reservation_type")

        if stock_batch_id is not None:
            batch = locked_batches.get(stock_batch_id)
            if not batch:
                raise HTTPException(404, f"Stock batch #{stock_batch_id} not found")
            if int(batch.item_id) != int(item_id):
                raise HTTPException(400, f"Batch {batch.batch_no} does not belong to item {item.sku}")
            if str(batch.unit or "").strip() != unit:
                raise HTTPException(400, f"Batch {batch.batch_no} unit is {batch.unit}, not {unit}")
            if warehouse_id is not None and int(batch.warehouse_id) != warehouse_id:
                raise HTTPException(400, f"Batch {batch.batch_no} is not in warehouse #{warehouse_id}")
            if unit != item_unit:
                raise HTTPException(400, f"Item {item.sku} unit is {item_unit}, not {unit}")
            warehouse_id = int(batch.warehouse_id)
            availability_key = ("batch", int(batch.id), None)
            available = float(batch.quantity or 0) - batch_reserved.get(int(batch.id), 0.0)
        else:
            if warehouse_id is not None and warehouse_id not in warehouses:
                raise HTTPException(404, f"Warehouse #{warehouse_id} not found")
            if unit != item_unit:
                raise HTTPException(400, f"Item {item.sku} unit is {item_unit}, not {unit}")
            availability_key = ("item", item_id, warehouse_id)
            available = available_by_key.get((item_id, warehouse_id), 0.0)
        available -= used_by_key.get(availability_key, 0.0)
        if quantity > available + EPSILON:
            if stock_batch_id is not None:
                raise HTTPException(
                    409,
                    f"Cannot reserve {quantity:g} {unit} from batch {batch.batch_no}; available unreserved quantity is {available:g}",
                )
            raise HTTPException(
                409,
                f"Cannot reserve {quantity:g} {unit} for item {item.sku}; available unreserved quantity is {available:g}",
            )

        used_by_key[availability_key] = used_by_key.get(availability_key, 0.0) + quantity

        reservation_values.append({
            "production_order_id": int(po.id),
            "sales_order_id": int(po.sales_order_id) if po.sales_order_id else None,
            "item_id": item_id,
            "stock_batch_id": stock_batch_id,
            "warehouse_id": warehouse_id,
            "reserved_quantity": quantity,
            "consumed_quantity": 0,
            "released_quantity": 0,
            "unit": unit,
            "status": "reserved",
            "reservation_type": reservation_type,
            "source": source,
            "reserved_by": user_id,
            "reserved_at": datetime.now(timezone.utc),
            "notes": notes,
        })

    reservation_nos = next_material_reservation_nos(db, len(reservation_values))
    created = [
        MaterialReservation(reservation_no=reservation_no, **values)
        for reservation_no, values in zip(reservation_nos, reservation_values, strict=True)
    ]
    db.add_all(created)
    db.flush()
    return created


def _set_reservation_status(reservation: MaterialReservation) -> None:
    remaining = _open_reservation_quantity(reservation)
    consumed = float(reservation.consumed_quantity or 0)
    released = float(reservation.released_quantity or 0)
    if remaining <= EPSILON:
        reservation.status = "released" if released > EPSILON else "consumed"
    elif consumed > EPSILON:
        reservation.status = "partially_consumed"
    else:
        reservation.status = "reserved"


def _consume_loaded_material_reservation(
    db: Session,
    reservation: MaterialReservation,
    *,
    quantity: float,
    user_id: int | None,
    reference_type: str,
    reference_id: int | None,
    stock_batch_cache: dict[int, StockBatch] | None = None,
    item_cache: dict[int, Item] | None = None,
) -> MaterialReservation:
    if reservation.status not in ACTIVE_RESERVATION_STATUSES:
        raise HTTPException(409, f"Reservation is not active (status: {reservation.status})")
    quantity = float(quantity or 0)
    if quantity <= 0:
        raise HTTPException(400, "Consume quantity must be greater than zero")
    remaining = _open_reservation_quantity(reservation)
    if quantity > remaining + EPSILON:
        raise HTTPException(409, f"Consume quantity exceeds remaining reserved quantity ({remaining:g})")

    if item_cache is None:
        reservation_item = reservation.item
        if reservation_item is not None:
            item_cache = {int(reservation_item.id): reservation_item}

    movement_reference_id = int(reference_id) if reference_id is not None else int(reservation.id)
    if reservation.stock_batch_id:
        consume_stock_batch(
            db,
            batch_id=int(reservation.stock_batch_id),
            quantity=quantity,
            unit=reservation.unit,
            reference_type=reference_type,
            reference_id=movement_reference_id,
            user_id=user_id,
            batch_cache=stock_batch_cache,
            item_cache=item_cache,
        )
    else:
        consume_item_from_batches(
            db,
            item_id=int(reservation.item_id),
            quantity=quantity,
            unit=reservation.unit,
            reference_type=reference_type,
            reference_id=movement_reference_id,
            user_id=user_id,
            warehouse_id=int(reservation.warehouse_id) if reservation.warehouse_id else None,
            require_available=True,
            item_cache=item_cache,
        )

    reservation.consumed_quantity = float(reservation.consumed_quantity or 0) + quantity
    _set_reservation_status(reservation)
    db.flush()
    return reservation


def _locked_material_reservation(db: Session, reservation_id: int) -> MaterialReservation | None:
    # populate_existing must not overwrite a caller's pending correction.
    db.flush()
    return (
        db.query(MaterialReservation)
        .options(
            lazyload(MaterialReservation.item),
            lazyload(MaterialReservation.stock_batch),
            lazyload(MaterialReservation.warehouse),
        )
        .filter(MaterialReservation.id == reservation_id)
        .populate_existing()
        .with_for_update(of=MaterialReservation)
        .first()
    )


def release_material_reservation(db: Session, reservation_id: int) -> MaterialReservation:
    reservation = _locked_material_reservation(db, reservation_id)
    if not reservation:
        raise HTTPException(404, "Material reservation not found")
    if reservation.status in ("cancelled", "released", "consumed"):
        raise HTTPException(409, f"Reservation is already {reservation.status}")
    remaining = _open_reservation_quantity(reservation)
    if remaining <= EPSILON:
        _set_reservation_status(reservation)
        db.flush()
        return reservation
    reservation.released_quantity = float(reservation.released_quantity or 0) + remaining
    _set_reservation_status(reservation)
    db.flush()
    return reservation


def consume_material_reservation(
    db: Session,
    reservation_id: int,
    *,
    quantity: float,
    user_id: int | None,
    reference_type: str = "MaterialReservation",
    reference_id: int | None = None,
) -> MaterialReservation:
    # All batch-backed reservation writers take the stock batch lock before
    # the reservation row; a plain get here permits stale remaining quantity.
    initial = db.query(MaterialReservation.stock_batch_id).filter(
        MaterialReservation.id == reservation_id,
    ).first()
    if initial is None:
        raise HTTPException(404, "Material reservation not found")
    batch_id = int(initial.stock_batch_id) if initial.stock_batch_id is not None else None
    stock_batch_cache, item_cache = _locked_stock_batches_for_consumption(
        db, [batch_id] if batch_id is not None else [],
    )
    reservation = _locked_material_reservation(db, reservation_id)
    if reservation is None:
        raise HTTPException(404, "Material reservation not found")
    if reservation.stock_batch_id != batch_id:
        raise HTTPException(409, "Material reservation batch changed; reload before consuming")
    return _consume_loaded_material_reservation(
        db,
        reservation,
        quantity=quantity,
        user_id=user_id,
        reference_type=reference_type,
        reference_id=reference_id,
        stock_batch_cache=stock_batch_cache,
        item_cache=item_cache,
    )


def _locked_reservations_by_stock_batch(
    db: Session,
    *,
    production_order_id: int,
    stock_batch_ids: list[int],
) -> dict[int, list[MaterialReservation]]:
    if not stock_batch_ids:
        return {}
    qry = (
        db.query(MaterialReservation)
        .options(
            lazyload(MaterialReservation.item),
            lazyload(MaterialReservation.stock_batch),
            lazyload(MaterialReservation.warehouse),
        )
        .filter(
            MaterialReservation.production_order_id == production_order_id,
            MaterialReservation.stock_batch_id.in_(stock_batch_ids),
            MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        )
        .order_by(
            MaterialReservation.stock_batch_id.asc(),
            MaterialReservation.created_at.asc(),
            MaterialReservation.id.asc(),
        )
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.with_for_update(of=MaterialReservation)
    by_batch: dict[int, list[MaterialReservation]] = {batch_id: [] for batch_id in stock_batch_ids}
    for reservation in qry.all():
        by_batch[int(reservation.stock_batch_id)].append(reservation)
    return by_batch


def _locked_stock_batches_for_consumption(
    db: Session,
    stock_batch_ids: list[int],
) -> tuple[dict[int, StockBatch], dict[int, Item]]:
    if not stock_batch_ids:
        return {}, {}
    # Do not let populate_existing discard stock changes already staged by the caller.
    db.flush()
    qry = (
        db.query(StockBatch)
        .options(lazyload(StockBatch.item))
        .filter(StockBatch.id.in_(stock_batch_ids))
        .order_by(StockBatch.id.asc())
        .populate_existing()
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.with_for_update(of=StockBatch)
    batches = {int(batch.id): batch for batch in qry.all()}
    item_ids = sorted({int(batch.item_id) for batch in batches.values()})
    items = {
        int(item.id): item
        for item in db.query(Item).filter(Item.id.in_(item_ids)).all()
    }
    return batches, items


def _require_full_reservation(
    reservations: list[MaterialReservation],
    *,
    quantity: float,
) -> None:
    reserved_available = sum(_open_reservation_quantity(row) for row in reservations)
    if reserved_available + EPSILON < quantity:
        raise HTTPException(
            409,
            f"Insufficient material reservation for cutting: reserved {reserved_available:g}, requested {quantity:g} "
            "for this production order and fabric batch.",
        )


def _consume_loaded_stock_batch_reservations(
    db: Session,
    reservations: list[MaterialReservation],
    *,
    quantity: float,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
    require_full: bool,
    stock_batch_cache: dict[int, StockBatch],
    item_cache: dict[int, Item],
) -> float:
    if require_full:
        _require_full_reservation(reservations, quantity=quantity)
    left = quantity
    consumed = 0.0
    for reservation in reservations:
        if left <= EPSILON:
            break
        take = min(left, _open_reservation_quantity(reservation))
        if take <= EPSILON:
            continue
        _consume_loaded_material_reservation(
            db,
            reservation,
            quantity=take,
            user_id=user_id,
            reference_type=reference_type,
            reference_id=reference_id,
            stock_batch_cache=stock_batch_cache,
            item_cache=item_cache,
        )
        consumed += take
        left -= take
    return consumed


def consume_material_reservations_for_stock_batch(
    db: Session,
    *,
    production_order_id: int,
    stock_batch_id: int,
    quantity: float,
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
    require_full: bool = False,
) -> float:
    quantity = float(quantity or 0)
    if quantity <= 0:
        return 0.0
    stock_batch_cache, item_cache = _locked_stock_batches_for_consumption(db, [stock_batch_id])
    reservations = _locked_reservations_by_stock_batch(
        db,
        production_order_id=production_order_id,
        stock_batch_ids=[stock_batch_id],
    ).get(stock_batch_id, [])
    if require_full:
        _require_full_reservation(reservations, quantity=quantity)
    if not reservations:
        return 0.0
    return _consume_loaded_stock_batch_reservations(
        db,
        reservations,
        quantity=quantity,
        reference_type=reference_type,
        reference_id=reference_id,
        user_id=user_id,
        require_full=False,
        stock_batch_cache=stock_batch_cache,
        item_cache=item_cache,
    )


def consume_cutting_materials(
    db: Session,
    *,
    production_order_id: int,
    lines: list[dict],
    reference_type: str,
    reference_id: int | None,
    user_id: int | None,
    require_full: bool = False,
) -> None:
    """Consume one cutting request with set-based locks and input-order effects."""
    if not lines:
        return
    db.flush()
    stock_batch_ids = sorted({int(line["stock_batch_id"]) for line in lines})
    stock_batch_cache, item_cache = _locked_stock_batches_for_consumption(db, stock_batch_ids)
    reservations_by_batch = _locked_reservations_by_stock_batch(
        db,
        production_order_id=production_order_id,
        stock_batch_ids=stock_batch_ids,
    )
    if require_full:
        remaining_reserved = {
            batch_id: sum(
                _open_reservation_quantity(reservation)
                for reservation in reservations_by_batch.get(batch_id, [])
            )
            for batch_id in stock_batch_ids
        }
        for line in lines:
            batch_id = int(line["stock_batch_id"])
            quantity = float(line["quantity"])
            available = remaining_reserved.get(batch_id, 0.0)
            if available + EPSILON < quantity:
                raise HTTPException(
                    409,
                    f"Insufficient material reservation for cutting: reserved {available:g}, requested {quantity:g} "
                    "for this production order and fabric batch.",
                )
            remaining_reserved[batch_id] = max(0.0, available - quantity)

    for line in lines:
        batch_id = int(line["stock_batch_id"])
        input_quantity = float(line["quantity"])
        reserved_consumed = _consume_loaded_stock_batch_reservations(
            db,
            reservations_by_batch.get(batch_id, []),
            quantity=input_quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            require_full=False,
            stock_batch_cache=stock_batch_cache,
            item_cache=item_cache,
        )
        direct_quantity = input_quantity - reserved_consumed
        if direct_quantity <= EPSILON:
            continue
        consume_stock_batch(
            db,
            batch_id=batch_id,
            quantity=direct_quantity,
            unit=str(line["unit"]),
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_id,
            batch_cache=stock_batch_cache,
            item_cache=item_cache,
        )


def auto_reserve_materials_for_production_order(
    db: Session,
    *,
    production_order_id: int,
    mode: str = "full_remaining",
    reserve_accessories: bool = True,
    reserve_materials: bool = True,
    reserve_packaging: bool = True,
    user_id: int | None,
) -> dict:
    if mode not in {"shortage_only", "full_remaining"}:
        raise HTTPException(400, "mode must be shortage_only or full_remaining")
    plan = reservation_plan_for_production_order(db, production_order_id)
    selected_types: set[str] = set()
    if reserve_materials:
        selected_types.add("material")
    if reserve_accessories:
        selected_types.add("accessory")
    if reserve_packaging:
        selected_types.add("packaging")
    lines: list[dict] = []
    for row in plan["rows"]:
        if row["reservation_type"] not in selected_types:
            continue
        if mode == "shortage_only" and float(row.get("shortage") or 0) <= EPSILON:
            continue
        for batch in row.get("suggested_batches") or []:
            qty = float(batch.get("suggested_quantity") or 0)
            if qty <= EPSILON:
                continue
            lines.append({
                "item_id": row["item_id"],
                "stock_batch_id": batch["stock_batch_id"],
                "warehouse_id": batch["warehouse_id"],
                "reserved_quantity": qty,
                "unit": row["unit"],
                "reservation_type": row["reservation_type"],
                "notes": "Auto reserved from BOM requirement",
            })
    created = create_material_reservations(
        db,
        production_order_id=production_order_id,
        lines=lines,
        user_id=user_id,
        source="auto_bom",
    ) if lines else []
    refreshed_plan = reservation_plan_for_production_order(db, production_order_id)
    shortage = float(refreshed_plan.get("summary", {}).get("shortage") or 0)
    if shortage > EPSILON:
        notify_department(
            db,
            department_code="PLN",
            title="Material reservation shortage",
            message=f"Production order {refreshed_plan.get('order_no') or production_order_id} still has material shortages.",
            link=f"/production-orders/{production_order_id}",
        )
        notify_department(
            db,
            department_code="STR",
            title="Material reservation shortage",
            message=f"Production order {refreshed_plan.get('order_no') or production_order_id} needs more stock to reserve.",
            link="/inventory?group=materials",
        )
    return {
        "production_order_id": production_order_id,
        "created_count": len(created),
        "reservations": created,
        "plan": refreshed_plan,
    }


def material_reservation_status_for_production_order(db: Session, production_order_id: int) -> dict:
    plan = reservation_plan_for_production_order(db, production_order_id)
    reservations = (
        db.query(MaterialReservation)
        .filter(MaterialReservation.production_order_id == production_order_id)
        .order_by(MaterialReservation.created_at.desc(), MaterialReservation.id.desc())
        .all()
    )
    active_reserved = sum(
        _open_reservation_quantity(row)
        for row in reservations
        if row.status in ACTIVE_RESERVATION_STATUSES
    )
    consumed = sum(float(row.consumed_quantity or 0) for row in reservations)
    released = sum(float(row.released_quantity or 0) for row in reservations)
    return {
        "plan": plan,
        "summary": {
            **plan["summary"],
            "active_reserved_quantity": active_reserved,
            "consumed_quantity": consumed,
            "released_quantity": released,
            "reservation_count": len(reservations),
        },
        "reservations": reservations,
    }


def require_material_reservation_before_cutting(db: Session) -> bool:
    row = db.query(SystemSetting).filter(SystemSetting.key == "preferences").first()
    if not row or not isinstance(row.value_json, dict):
        return False
    return bool(row.value_json.get(REQUIRE_RESERVATION_SETTING, False))


def missing_material_reservation_for_cutting(db: Session, production_order_id: int) -> bool:
    if not require_material_reservation_before_cutting(db):
        return False
    plan = reservation_plan_for_production_order(db, production_order_id)
    return not bool(plan.get("is_complete"))


def _stock_item_query(
    db: Session,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
):
    positive_batch_exists = db.query(StockBatch.id).filter(
        StockBatch.item_id == Item.id,
        StockBatch.quantity > 0,
    ).exists()
    active_reservation_exists = db.query(MaterialReservation.id).filter(
        MaterialReservation.item_id == Item.id,
        MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        (
            MaterialReservation.reserved_quantity
            - MaterialReservation.consumed_quantity
            - MaterialReservation.released_quantity
        ) > 0,
    ).exists()
    batchless_movement_exists = db.query(StockMovement.id).filter(
        StockMovement.item_id == Item.id,
        StockMovement.batch_id.is_(None),
    ).exists()
    query = db.query(Item).filter(
        or_(
            Item.is_active.is_(True),
            positive_batch_exists,
            active_reservation_exists,
            batchless_movement_exists,
        )
    )
    categories = categories_for_group(group)
    if categories:
        query = query.filter(Item.category.in_(categories))
    if category:
        query = query.filter(Item.category == category)
    if supplier_id or created_from or created_to:
        matching_batch_items = db.query(StockBatch.item_id)
        if supplier_id:
            matching_batch_items = matching_batch_items.filter(StockBatch.supplier_id == supplier_id)
        if created_from:
            matching_batch_items = matching_batch_items.filter(StockBatch.received_date >= created_from)
        if created_to:
            matching_batch_items = matching_batch_items.filter(StockBatch.received_date <= created_to)
        query = query.filter(Item.id.in_(matching_batch_items))
    search = (q or "").strip()
    if search:
        term = f"%{search}%"
        matching_batch_items = db.query(StockBatch.item_id).filter(
            StockBatch.quantity > 0,
            or_(
                StockBatch.batch_no.ilike(term),
                StockBatch.color.ilike(term),
                StockBatch.old_code.ilike(term),
                StockBatch.color_code.ilike(term),
                StockBatch.color_status.ilike(term),
                StockBatch.order_no.ilike(term),
                StockBatch.processes.ilike(term),
                StockBatch.unit.ilike(term),
                StockBatch.qc_status.ilike(term),
            )
        )
        query = query.filter(
            or_(
                Item.sku.ilike(term),
                Item.name.ilike(term),
                Item.unit.ilike(term),
                Item.id.in_(matching_batch_items),
            )
        )
    return query


def stock_summary_count(
    db: Session,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> int:
    return int(_stock_item_query(db, category=category, group=group, q=q, supplier_id=supplier_id, created_from=created_from, created_to=created_to).count())


def stock_summary(
    db: Session,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int | None = None,
    page_size: int | None = None,
    include_total: bool = False,
) -> list[dict] | tuple[list[dict], int]:
    latest_batch_query = (
        db.query(
            StockBatch.item_id.label("item_id"),
            func.max(StockBatch.received_date).label("received_at"),
        )
    )
    if supplier_id:
        latest_batch_query = latest_batch_query.filter(StockBatch.supplier_id == supplier_id)
    if created_from:
        latest_batch_query = latest_batch_query.filter(StockBatch.received_date >= created_from)
    if created_to:
        latest_batch_query = latest_batch_query.filter(StockBatch.received_date <= created_to)
    latest_batch_receipt = latest_batch_query.group_by(StockBatch.item_id).subquery()
    query = _stock_item_query(
        db,
        category=category,
        group=group,
        q=q,
        supplier_id=supplier_id,
        created_from=created_from,
        created_to=created_to,
    ).options(
        load_only(
            Item.id,
            Item.sku,
            Item.name,
            Item.image_url,
            Item.category,
            Item.unit,
            raiseload=True,
        )
    ).outerjoin(latest_batch_receipt, latest_batch_receipt.c.item_id == Item.id)
    query = query.order_by(
        func.coalesce(latest_batch_receipt.c.received_at, Item.created_at).desc(),
        Item.id.desc(),
    )
    if include_total:
        query = query.add_columns(func.count(Item.id).over().label("page_total"))
    if page is not None or page_size is not None:
        safe_page, safe_size, offset = clamp_pagination(page or 1, page_size or 50)
        query = query.offset(offset).limit(safe_size)
    raw_items = query.all()
    total = 0
    if include_total:
        total = int(raw_items[0][1] or 0) if raw_items else 0
        items = [row[0] for row in raw_items]
        if not items and (page or 1) > 1:
            total = stock_summary_count(
                db,
                category=category,
                group=group,
                q=q,
                supplier_id=supplier_id,
                created_from=created_from,
                created_to=created_to,
            )
    else:
        items = raw_items
    if not items:
        return ([], total) if include_total else []

    item_ids = [it.id for it in items]
    batch_query = (
        db.query(StockBatch.item_id, func.coalesce(func.sum(StockBatch.quantity), 0))
        .filter(StockBatch.item_id.in_(item_ids))
    )
    if supplier_id:
        batch_query = batch_query.filter(StockBatch.supplier_id == supplier_id)
    if created_from:
        batch_query = batch_query.filter(StockBatch.received_date >= created_from)
    if created_to:
        batch_query = batch_query.filter(StockBatch.received_date <= created_to)
    batch_rows = batch_query.group_by(StockBatch.item_id).all()
    if supplier_id or created_from or created_to:
        move_rows = []
        reservation_rows = []
    else:
        move_rows = (
            db.query(StockMovement.item_id, StockMovement.movement_type, func.coalesce(func.sum(StockMovement.quantity), 0))
            .filter(StockMovement.item_id.in_(item_ids), StockMovement.batch_id.is_(None))
            .group_by(StockMovement.item_id, StockMovement.movement_type)
            .all()
        )
        reservation_rows = (
            db.query(MaterialReservation.item_id, _active_reserved_sum_query(db))
            .filter(
                MaterialReservation.item_id.in_(item_ids),
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            )
            .group_by(MaterialReservation.item_id)
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
    reserved_totals = {int(item_id): max(0.0, float(qty or 0)) for item_id, qty in reservation_rows}

    out = []
    for it in items:
        qty = batch_totals.get(it.id, 0.0) + deltas.get(it.id, 0.0)
        reserved_qty = reserved_totals.get(it.id, 0.0)
        out.append({
            "item_id": it.id,
            "sku": it.sku,
            "name": it.name,
            "image_url": it.image_url,
            "category": it.category,
            "unit": it.unit,
            "quantity": qty,
            "reserved_quantity": reserved_qty,
            "available_quantity": qty - reserved_qty,
        })
    return (out, total) if include_total else out


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


def lock_accessory_return_allowance(db: Session, production_order_id: int) -> None:
    """Serialize dedicated return requests through replay, allowance and commit.

    This independent order-level lock does not acquire the order row or any
    batch/item/numbering lock used by reservations. PostgreSQL releases it on
    commit or rollback; other issue/movement writers do not participate.
    """
    if db.bind and db.bind.dialect.name == "postgresql":
        # Read the stored integer key so nonexistent/out-of-range IDs retain
        # the route's normal 404 behavior instead of overflowing the lock key.
        db.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, id) FROM production_orders WHERE id = :order_id"),
            {"namespace": _ACCESSORY_RETURN_LOCK_NAMESPACE, "order_id": production_order_id},
        )


def _accessory_returnable_summary_page_sql(
    db: Session,
    *,
    production_order_id: int | None,
    model_id: int | None,
    q: str | None,
    page: int,
    page_size: int,
    orders_only: bool,
) -> tuple[list[dict], int]:
    """Aggregate return-picker source rows in SQL before counting or paging.

    Keep this projection separate from the compatibility summary below: the
    picker only needs catalog-linked rows with a positive net return balance.
    """
    movement_unit = func.coalesce(func.nullif(func.trim(StockMovement.unit), ""), Item.unit)
    movement_base = (
        db.query(
            StockMovement.item_id.label("item_id"),
            movement_unit.label("unit"),
            StockMovement.quantity.label("quantity"),
            StockMovement.created_at.label("created_at"),
            literal(1).label("is_stock"),
            literal(None, type_=String()).label("manual_item_sku"),
            literal(None, type_=String()).label("manual_item_name"),
        )
        .join(Item, Item.id == StockMovement.item_id)
        .filter(
            Item.category.in_(ACCESSORY_CATEGORIES),
            StockMovement.movement_type.in_(("consume", "issue")),
        )
    )
    movement_sources = [
        movement_base.with_entities(
            StockMovement.reference_id.label("production_order_id"),
            *movement_base.statement.selected_columns,
        ).filter(StockMovement.reference_type.in_(("ProductionOrder", "ProductionOrderAccessoryIssue"))),
        movement_base.join(
            WorkOrder,
            and_(
                StockMovement.reference_type == "WorkOrder",
                StockMovement.reference_id == WorkOrder.id,
            ),
        ).with_entities(
            WorkOrder.production_order_id.label("production_order_id"),
            StockMovement.item_id.label("item_id"), movement_unit.label("unit"),
            StockMovement.quantity.label("quantity"), StockMovement.created_at.label("created_at"),
            literal(1).label("is_stock"), literal(None, type_=String()).label("manual_item_sku"),
            literal(None, type_=String()).label("manual_item_name"),
        ),
    ]
    record_mappings = (
        ("CuttingRecord", CuttingRecord),
        ("SewingRecord", SewingRecord),
        ("PackagingRecord", PackagingRecord),
    )
    for reference_type, record_model in record_mappings:
        movement_sources.append(
            movement_base.join(
                record_model,
                and_(
                    StockMovement.reference_type == reference_type,
                    StockMovement.reference_id == record_model.id,
                ),
            ).join(WorkOrder, WorkOrder.id == record_model.work_order_id).with_entities(
                WorkOrder.production_order_id.label("production_order_id"),
                StockMovement.item_id.label("item_id"), movement_unit.label("unit"),
                StockMovement.quantity.label("quantity"), StockMovement.created_at.label("created_at"),
                literal(1).label("is_stock"), literal(None, type_=String()).label("manual_item_sku"),
                literal(None, type_=String()).label("manual_item_name"),
            )
        )

    manual_unit = func.coalesce(func.nullif(func.trim(ManualAccessoryIssue.unit), ""), "pcs")
    # This is an actionable return picker, not the compatibility issue ledger:
    # the return route rejects catalog items outside these categories.
    manual_rows = (
        db.query(
            ManualAccessoryIssue.production_order_id.label("production_order_id"),
            ManualAccessoryIssue.item_id.label("item_id"),
            manual_unit.label("unit"),
            ManualAccessoryIssue.quantity.label("quantity"),
            ManualAccessoryIssue.created_at.label("created_at"),
            literal(0).label("is_stock"),
            ManualAccessoryIssue.item_sku.label("manual_item_sku"),
            ManualAccessoryIssue.item_name.label("manual_item_name"),
        )
        .join(Item, Item.id == ManualAccessoryIssue.item_id)
        .filter(Item.category.in_(ACCESSORY_CATEGORIES), ManualAccessoryIssue.item_id.is_not(None))
    )
    if production_order_id is not None:
        manual_rows = manual_rows.filter(ManualAccessoryIssue.production_order_id == production_order_id)
    event_sources = [source.statement for source in movement_sources]
    event_sources.append(manual_rows.statement)
    events = union_all(*event_sources).cte("accessory_return_events")

    grouped_query = db.query(
        events.c.production_order_id.label("production_order_id"),
        events.c.item_id.label("item_id"),
        events.c.unit.label("unit"),
        func.sum(events.c.quantity).label("issued_quantity"),
        func.sum(events.c.is_stock).label("stock_movement_count"),
        func.count().label("movement_count"),
        func.min(events.c.created_at).label("first_issued_at"),
        func.max(events.c.created_at).label("last_issued_at"),
    ).group_by(events.c.production_order_id, events.c.item_id, events.c.unit)
    if production_order_id is not None:
        grouped_query = grouped_query.filter(events.c.production_order_id == production_order_id)
    grouped = grouped_query.cte("accessory_return_groups")

    manual_rank = func.row_number().over(
        partition_by=(
            ManualAccessoryIssue.production_order_id,
            ManualAccessoryIssue.item_id,
            manual_unit,
        ),
        order_by=(ManualAccessoryIssue.created_at.desc(), ManualAccessoryIssue.id.desc()),
    ).label("manual_rank")
    latest_manual = (
        db.query(
            ManualAccessoryIssue.production_order_id.label("production_order_id"),
            ManualAccessoryIssue.item_id.label("item_id"),
            manual_unit.label("unit"),
            ManualAccessoryIssue.item_sku.label("item_sku"),
            ManualAccessoryIssue.item_name.label("item_name"),
            manual_rank,
        )
        .filter(ManualAccessoryIssue.item_id.is_not(None))
        .subquery("accessory_return_latest_manual")
    )
    return_totals = (
        db.query(
            StockMovement.reference_id.label("production_order_id"),
            StockMovement.item_id.label("item_id"),
            StockMovement.unit.label("unit"),
            func.sum(StockMovement.quantity).label("returned_quantity"),
        )
        .join(
            grouped,
            and_(
                grouped.c.production_order_id == StockMovement.reference_id,
                grouped.c.item_id == StockMovement.item_id,
                grouped.c.unit == StockMovement.unit,
            ),
        )
        .filter(
            StockMovement.movement_type == "return",
            StockMovement.reference_type == "ProductionOrderAccessoryReturn",
        )
        .group_by(StockMovement.reference_id, StockMovement.item_id, StockMovement.unit)
        .cte("accessory_return_totals")
    )

    effective_manual_sku = func.nullif(func.trim(func.coalesce(latest_manual.c.item_sku, "")), "")
    effective_manual_name = func.coalesce(
        func.nullif(func.trim(func.coalesce(latest_manual.c.item_name, "")), ""),
        effective_manual_sku,
        "Manual accessory",
    )
    item_sku = case(
        (grouped.c.stock_movement_count > 0, Item.sku),
        else_=func.coalesce(effective_manual_sku, effective_manual_name),
    )
    item_name = case(
        (grouped.c.stock_movement_count > 0, Item.name),
        else_=effective_manual_name,
    )
    returned = func.coalesce(return_totals.c.returned_quantity, 0.0)
    returnable = grouped.c.issued_quantity - returned
    rows_query = db.query(
        grouped.c.production_order_id,
        ProductionOrder.production_no,
        SalesOrder.order_no,
        ProductionOrder.model_id,
        Model.code.label("model_code"),
        Model.name.label("model_name"),
        grouped.c.item_id,
        item_sku.label("item_sku"),
        item_name.label("item_name"),
        Item.image_url.label("item_image_url"),
        Item.category.label("category"),
        grouped.c.unit,
        grouped.c.issued_quantity,
        returned.label("returned_quantity"),
        case((returnable > EPSILON, returnable), else_=0.0).label("returnable_quantity"),
        grouped.c.movement_count,
        grouped.c.first_issued_at,
        grouped.c.last_issued_at,
    )
    rows_query = (
        rows_query.join(ProductionOrder, ProductionOrder.id == grouped.c.production_order_id)
        .outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
        .outerjoin(Model, Model.id == ProductionOrder.model_id)
        .join(Item, Item.id == grouped.c.item_id)
        .outerjoin(
            latest_manual,
            and_(
                latest_manual.c.production_order_id == grouped.c.production_order_id,
                latest_manual.c.item_id == grouped.c.item_id,
                latest_manual.c.unit == grouped.c.unit,
                latest_manual.c.manual_rank == 1,
            ),
        )
        .outerjoin(
            return_totals,
            and_(
                return_totals.c.production_order_id == grouped.c.production_order_id,
                return_totals.c.item_id == grouped.c.item_id,
                return_totals.c.unit == grouped.c.unit,
            ),
        )
        # The return write requires the item's canonical unit; keep the legacy
        # issue projection's historical alternate-unit groups untouched.
        .filter(
            Item.category.in_(ACCESSORY_CATEGORIES),
            func.trim(grouped.c.unit) == Item.unit,
            returnable > EPSILON,
        )
    )
    if production_order_id is not None:
        rows_query = rows_query.filter(ProductionOrder.id == production_order_id)
    if model_id is not None:
        rows_query = rows_query.filter(ProductionOrder.model_id == model_id)
    search = (q or "").strip().lower()
    if search:
        escaped_search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_search}%"
        search_filters = [
            func.lower(func.coalesce(SalesOrder.order_no, "")).like(pattern, escape="\\"),
            func.lower(ProductionOrder.production_no).like(pattern, escape="\\"),
            func.lower(func.coalesce(Model.name, "")).like(pattern, escape="\\"),
            func.lower(func.coalesce(item_sku, "")).like(pattern, escape="\\"),
            func.lower(func.coalesce(item_name, "")).like(pattern, escape="\\"),
            func.lower(grouped.c.unit).like(pattern, escape="\\"),
        ]
        normalized_query = normalized_model_code_key(search)
        if normalized_query:
            search_filters.append(normalized_model_code_column(Model.code).like(f"%{normalized_query}%"))
        rows_query = rows_query.filter(or_(*search_filters))

    rows_subquery = rows_query.subquery("accessory_return_filtered_groups")
    if orders_only:
        order_rank = func.row_number().over(
            partition_by=rows_subquery.c.production_order_id,
            order_by=(
                rows_subquery.c.last_issued_at.desc(),
                rows_subquery.c.production_order_id.desc(),
                rows_subquery.c.item_sku.desc(),
                rows_subquery.c.item_id.desc(),
                rows_subquery.c.unit.desc(),
            ),
        ).label("order_rank")
        ranked = db.query(rows_subquery, order_rank).subquery("accessory_return_order_choices")
        rows_subquery = db.query(ranked).filter(ranked.c.order_rank == 1).subquery("accessory_return_unique_orders")

    total = int(db.query(func.count()).select_from(rows_subquery).scalar() or 0)
    safe_page, safe_size, offset = clamp_pagination(page, page_size)
    page_rows = (
        db.query(rows_subquery)
        .order_by(
            rows_subquery.c.last_issued_at.desc(),
            rows_subquery.c.production_order_id.desc(),
            rows_subquery.c.item_sku.desc(),
            rows_subquery.c.item_id.desc(),
            rows_subquery.c.unit.desc(),
        )
        .offset(offset)
        .limit(safe_size)
        .all()
    )
    keys = (
        "production_order_id", "production_no", "order_no", "model_id", "model_code", "model_name",
        "item_id", "item_sku", "item_name", "item_image_url", "category", "unit", "issued_quantity",
        "returned_quantity", "returnable_quantity", "movement_count", "first_issued_at", "last_issued_at",
    )
    projected = []
    for row in page_rows:
        record = row._mapping
        projected.append({key: record[key] for key in keys})
    return projected, total


def accessory_issue_summary(
    db: Session,
    *,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    include_total: bool = False,
    returnable_only: bool = False,
    orders_only: bool = False,
) -> list[dict] | tuple[list[dict], int]:
    if include_total and returnable_only:
        return _accessory_returnable_summary_page_sql(
            db,
            production_order_id=production_order_id,
            model_id=model_id,
            q=q,
            page=page or 1,
            page_size=page_size or 50,
            orders_only=orders_only,
        )
    exact_page = include_total or returnable_only or orders_only
    query = (
        db.query(StockMovement, Item)
        .options(
            load_only(
                StockMovement.id,
                StockMovement.reference_type,
                StockMovement.reference_id,
                StockMovement.unit,
                StockMovement.created_at,
                StockMovement.quantity,
            ),
            load_only(Item.id, Item.unit, Item.sku, Item.name, Item.image_url, Item.category),
        )
        .join(Item, Item.id == StockMovement.item_id)
        .filter(
            Item.category.in_(ACCESSORY_CATEGORIES),
            StockMovement.movement_type.in_(("consume", "issue")),
        )
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
    )
    if not exact_page and (page is not None or page_size is not None):
        safe_page, safe_size, _ = clamp_pagination(page or 1, page_size or 50)
        query = query.limit(max(safe_page * safe_size * 20, safe_size))
    movements_with_items = query.all()
    movements = [movement for movement, _ in movements_with_items]
    po_ids_by_movement_id = _movement_production_order_ids(db, movements)

    manual_query = db.query(ManualAccessoryIssue).order_by(
        ManualAccessoryIssue.created_at.desc(),
        ManualAccessoryIssue.id.desc(),
    )
    if production_order_id is not None:
        manual_query = manual_query.filter(ManualAccessoryIssue.production_order_id == production_order_id)
    if not exact_page and (page is not None or page_size is not None):
        safe_page, safe_size, _ = clamp_pagination(page or 1, page_size or 50)
        manual_query = manual_query.limit(max(safe_page * safe_size * 20, safe_size))
    manual_issues = manual_query.all()

    all_po_ids = set(po_ids_by_movement_id.values()) | {
        int(issue.production_order_id) for issue in manual_issues if issue.production_order_id
    }
    if not all_po_ids:
        return ([], 0) if include_total else []
    po_rows = (
        db.query(ProductionOrder)
        .options(
            load_only(
                ProductionOrder.id,
                ProductionOrder.model_id,
                ProductionOrder.production_no,
                ProductionOrder.sales_order_id,
            ),
            joinedload(ProductionOrder.sales_order).load_only(SalesOrder.id, SalesOrder.order_no),
            noload(ProductionOrder.materials),
        )
        .filter(ProductionOrder.id.in_(all_po_ids))
        .all()
    )
    po_by_id = {int(po.id): po for po in po_rows}

    model_ids = {int(po.model_id) for po in po_rows if po.model_id}
    models = (
        db.query(Model)
        .options(load_only(Model.id, Model.code, Model.name))
        .filter(Model.id.in_(model_ids))
        .all()
        if model_ids
        else []
    )
    model_by_id = {int(model.id): model for model in models}

    item_by_id: dict[int, Item] = {}
    grouped: dict[tuple[int, int, str] | tuple[int, int, str, str], dict] = {}
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
                "order_no": po.order_no,
                "model_id": int(po.model_id),
                "model_code": model.code if model else None,
                "model_name": model.name if model else None,
                "item_id": int(item.id),
                "item_sku": item.sku,
                "item_name": item.name,
                "item_image_url": item.image_url,
                "category": item.category,
                "unit": unit,
                "issued_quantity": 0.0,
                "returned_quantity": 0.0,
                "returnable_quantity": 0.0,
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

    for issue in manual_issues:
        po = po_by_id.get(int(issue.production_order_id))
        if not po:
            continue
        if production_order_id is not None and int(po.id) != int(production_order_id):
            continue
        if model_id is not None and int(po.model_id) != int(model_id):
            continue

        unit = str(issue.unit or "").strip() or "pcs"
        item_id = int(issue.item_id or 0)
        item_sku = str(issue.item_sku or "").strip()
        item_name = str(issue.item_name or "").strip() or item_sku or "Manual accessory"
        # Returns identify the order, catalog item and unit, not the issue source
        # or historical label. Merge linked manual issues before applying returns.
        key = ((int(po.id), item_id, unit) if item_id > 0 else
               (int(po.id), item_id, unit, _accessory_match_key(item_sku or item_name)))
        model = model_by_id.get(int(po.model_id))
        first_at = issue.created_at
        last_at = issue.created_at
        existing = grouped.get(key)
        if not existing:
            existing = {
                "production_order_id": int(po.id),
                "production_no": po.production_no,
                "order_no": po.order_no,
                "model_id": int(po.model_id),
                "model_code": model.code if model else None,
                "model_name": model.name if model else None,
                "item_id": item_id,
                "item_sku": item_sku or item_name,
                "item_name": item_name,
                "item_image_url": issue.item.image_url if issue.item else None,
                "category": issue.item.category if issue.item else "accessory",
                "unit": unit,
                "issued_quantity": 0.0,
                "returned_quantity": 0.0,
                "returnable_quantity": 0.0,
                "movement_count": 0,
                "first_issued_at": first_at,
                "last_issued_at": last_at,
            }
            grouped[key] = existing
        existing["issued_quantity"] += float(issue.quantity or 0)
        existing["movement_count"] += 1
        if first_at and (not existing["first_issued_at"] or first_at < existing["first_issued_at"]):
            existing["first_issued_at"] = first_at
        if last_at and (not existing["last_issued_at"] or last_at > existing["last_issued_at"]):
            existing["last_issued_at"] = last_at

    rows = list(grouped.values())
    if rows:
        po_ids = {int(row["production_order_id"]) for row in rows}
        item_ids = {int(row["item_id"]) for row in rows}
        return_rows = (
            db.query(
                StockMovement.reference_id,
                StockMovement.item_id,
                StockMovement.unit,
                func.coalesce(func.sum(StockMovement.quantity), 0),
            )
            .filter(
                StockMovement.movement_type == "return",
                StockMovement.reference_type == "ProductionOrderAccessoryReturn",
                StockMovement.reference_id.in_(po_ids),
                StockMovement.item_id.in_(item_ids),
            )
            .group_by(StockMovement.reference_id, StockMovement.item_id, StockMovement.unit)
            .all()
        )
        returned_by_key = {
            (int(po_id), int(item_id), str(unit or "")): float(quantity or 0)
            for po_id, item_id, unit, quantity in return_rows
            if po_id and item_id
        }
        for row in rows:
            key = (int(row["production_order_id"]), int(row["item_id"]), str(row["unit"] or ""))
            returned = returned_by_key.get(key, 0.0)
            issued = float(row.get("issued_quantity") or 0)
            row["returned_quantity"] = returned
            row["returnable_quantity"] = max(0.0, issued - returned)

    search = (q or "").strip().lower()
    if search:
        def matches(row: dict) -> bool:
            if model_code_contains(row.get("model_code"), search):
                return True
            fields = [
                row.get("order_no"),
                row.get("production_no"),
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

    sorted_rows = sorted(rows, key=sort_key, reverse=True)
    if returnable_only:
        # A return requires a catalog item. Itemless historical manual issues
        # remain visible in the legacy summary, but cannot be received back.
        sorted_rows = [
            row for row in sorted_rows
            if int(row.get("item_id") or 0) > 0
            and float(row.get("returnable_quantity") or 0) > EPSILON
        ]
    if orders_only:
        # The Receive/Return order selector displays unique orders, not issue
        # item groups, so its total and page boundaries must use that identity.
        first_row_by_order: dict[int, dict] = {}
        for row in sorted_rows:
            first_row_by_order.setdefault(int(row.get("production_order_id") or 0), row)
        sorted_rows = list(first_row_by_order.values())
    if page is not None or page_size is not None:
        safe_page, safe_size, offset = clamp_pagination(page or 1, page_size or 50)
        page_rows = sorted_rows[offset: offset + safe_size]
        if include_total:
            return page_rows, len(sorted_rows)
        return page_rows
    if include_total:
        return sorted_rows, len(sorted_rows)
    return sorted_rows


def _accessory_issue_plan_summary(rows: list[dict]) -> dict:
    total_required = sum(float(row.get("required_quantity") or 0) for row in rows)
    total_issued = sum(float(row.get("issued_quantity") or 0) for row in rows)
    total_remaining = sum(float(row.get("remaining_quantity") or 0) for row in rows)
    total_shortage = sum(float(row.get("shortage") or 0) for row in rows)
    if not rows:
        status = "no_bom"
    elif total_remaining <= EPSILON:
        status = "ready"
    elif total_shortage > EPSILON:
        status = "shortage"
    else:
        status = "partial"
    return {
        "status": status,
        "is_complete": total_remaining <= EPSILON,
        "warning": None if total_remaining <= EPSILON else ACCESSORY_SEWING_BLOCK_REASON,
        "summary": {
            "required_quantity": total_required,
            "issued_quantity": total_issued,
            "remaining_quantity": total_remaining,
            "available_quantity": sum(float(row.get("available_quantity") or 0) for row in rows),
            "shortage": total_shortage,
            "line_count": len(rows),
            "ready_line_count": sum(1 for row in rows if row.get("status") == "ready"),
            "shortage_line_count": sum(1 for row in rows if row.get("status") == "shortage"),
        },
    }


def _accessory_plan_quantity(value: object) -> Decimal:
    """Normalize quantities to the four decimal places stored by inventory."""
    return Decimal(str(value or 0)).quantize(_ACCESSORY_QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def accessory_issue_plan(db: Session, production_order_id: int) -> dict:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    model_code, model_name = _model_label_fields(db, po.model_id)
    required_rows = _bom_requirement_rows(db, po, ACCESSORY_CATEGORIES)

    issued_rows = accessory_issue_summary(db, production_order_id=po.id)
    issued_by_item_unit = {
        (int(row["item_id"]), str(row["unit"])): float(row["issued_quantity"] or 0)
        for row in issued_rows
        if int(row.get("item_id") or 0) > 0
    }
    manual_issued_by_label_unit: dict[tuple[str, str], float] = {}
    for issued_row in issued_rows:
        if int(issued_row.get("item_id") or 0) > 0:
            continue
        unit = str(issued_row.get("unit") or "")
        for value in (issued_row.get("item_sku"), issued_row.get("item_name")):
            key = _accessory_match_key(value)
            if not key:
                continue
            manual_issued_by_label_unit[(key, unit)] = manual_issued_by_label_unit.get((key, unit), 0.0) + float(
                issued_row.get("issued_quantity") or 0
            )

    available_by_item_id = available_stock_for_items(
        db,
        {int(row["item_id"]) for row in required_rows},
    )
    rows = []
    for row in required_rows:
        key = (int(row["item_id"]), str(row["unit"]))
        issued = _accessory_plan_quantity(issued_by_item_unit.get(key, 0.0))
        unit = str(row["unit"])
        for value in (row.get("item_sku"), row.get("item_name")):
            manual_key = (_accessory_match_key(value), unit)
            issued += _accessory_plan_quantity(manual_issued_by_label_unit.get(manual_key, 0.0))
        required = _accessory_plan_quantity(row["required_quantity"])
        available = _accessory_plan_quantity(available_by_item_id.get(int(row["item_id"]), 0.0))
        remaining = max(Decimal("0"), required - issued)
        shortage = max(Decimal("0"), remaining - available)
        if remaining == 0:
            status = "ready"
        elif shortage > 0:
            status = "shortage"
        else:
            status = "partial"
        rows.append({
            **row,
            "required_quantity": float(required),
            "issued_quantity": float(issued),
            "remaining_quantity": float(remaining),
            "available_quantity": float(available),
            "shortage": float(shortage),
            "status": status,
        })

    rows.sort(key=lambda row: (row["category"], row["item_sku"]))
    readiness = _accessory_issue_plan_summary(rows)
    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "model_id": int(po.model_id),
        "model_code": model_code,
        "model_name": model_name,
        "planned_quantity": int(po.planned_quantity or 0),
        "status": readiness["status"],
        "is_complete": readiness["is_complete"],
        "warning": readiness["warning"],
        "summary": readiness["summary"],
        "rows": rows,
    }


def _accessory_request_issue_totals(
    db: Session,
    production_order_ids: list[int],
) -> tuple[dict[tuple[int, int, str], float], dict[tuple[int, str, str], float]]:
    issued_by_item_unit: dict[tuple[int, int, str], float] = {}
    manual_by_label_unit: dict[tuple[int, str, str], float] = {}
    if not production_order_ids:
        return issued_by_item_unit, manual_by_label_unit

    work_order_to_po: dict[int, int] = {}
    for start in range(0, len(production_order_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = production_order_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        work_order_to_po.update({
            int(work_order_id): int(production_order_id)
            for work_order_id, production_order_id in db.query(
                WorkOrder.id,
                WorkOrder.production_order_id,
            ).filter(WorkOrder.production_order_id.in_(chunk)).all()
        })

    reference_to_po: dict[str, dict[int, int]] = {
        "WorkOrder": work_order_to_po,
        "CuttingRecord": {},
        "SewingRecord": {},
        "PackagingRecord": {},
    }
    work_order_ids = sorted(work_order_to_po)
    for record_type, model_cls in (
        ("CuttingRecord", CuttingRecord),
        ("SewingRecord", SewingRecord),
        ("PackagingRecord", PackagingRecord),
    ):
        mapping = reference_to_po[record_type]
        for start in range(0, len(work_order_ids), _BULK_STOCK_CHUNK_SIZE):
            chunk = work_order_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
            for record_id, work_order_id in db.query(model_cls.id, model_cls.work_order_id).filter(
                model_cls.work_order_id.in_(chunk)
            ).all():
                production_order_id = work_order_to_po.get(int(work_order_id))
                if production_order_id:
                    mapping[int(record_id)] = production_order_id

    def add_movement_rows(reference_types: tuple[str, ...], reference_to_order: dict[int, int]) -> None:
        reference_ids = sorted(reference_to_order)
        for start in range(0, len(reference_ids), _BULK_STOCK_CHUNK_SIZE):
            chunk = reference_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
            movement_rows = (
                db.query(
                    StockMovement.reference_id,
                    StockMovement.item_id,
                    StockMovement.unit,
                    Item.unit,
                    func.coalesce(func.sum(StockMovement.quantity), 0),
                )
                .join(Item, Item.id == StockMovement.item_id)
                .filter(
                    Item.category.in_(ACCESSORY_CATEGORIES),
                    StockMovement.movement_type.in_(("consume", "issue")),
                    StockMovement.reference_type.in_(reference_types),
                    StockMovement.reference_id.in_(chunk),
                )
                .group_by(
                    StockMovement.reference_id,
                    StockMovement.item_id,
                    StockMovement.unit,
                    Item.unit,
                )
                .all()
            )
            for reference_id, item_id, raw_unit, item_unit, quantity in movement_rows:
                production_order_id = reference_to_order.get(int(reference_id))
                if not production_order_id:
                    continue
                unit = str(raw_unit or item_unit or "").strip() or str(item_unit or "")
                key = (production_order_id, int(item_id), str(unit or ""))
                issued_by_item_unit[key] = issued_by_item_unit.get(key, 0.0) + float(quantity or 0)

    direct_to_po = {production_order_id: production_order_id for production_order_id in production_order_ids}
    add_movement_rows(("ProductionOrder", "ProductionOrderAccessoryIssue"), direct_to_po)
    for reference_type, mapping in reference_to_po.items():
        add_movement_rows((reference_type,), mapping)

    grouped_manual: dict[tuple[int, int, str] | tuple[int, int, str, str], dict] = {}
    for start in range(0, len(production_order_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = production_order_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        manual_rows = (
            db.query(
                ManualAccessoryIssue.production_order_id,
                ManualAccessoryIssue.item_id,
                ManualAccessoryIssue.item_sku,
                ManualAccessoryIssue.item_name,
                ManualAccessoryIssue.quantity,
                ManualAccessoryIssue.unit,
            )
            .filter(ManualAccessoryIssue.production_order_id.in_(chunk))
            .order_by(ManualAccessoryIssue.created_at.desc(), ManualAccessoryIssue.id.desc())
            .all()
        )
        for production_order_id, raw_item_id, item_sku, item_name, quantity, raw_unit in manual_rows:
            item_id = int(raw_item_id or 0)
            unit = str(raw_unit or "").strip() or "pcs"
            normalized_name = str(item_name or "").strip() or str(item_sku or "").strip() or "Manual accessory"
            normalized_sku = str(item_sku or "").strip()
            key = (
                (int(production_order_id), item_id, unit)
                if item_id > 0
                else (
                    int(production_order_id),
                    item_id,
                    unit,
                    _accessory_match_key(normalized_sku or normalized_name),
                )
            )
            grouped = grouped_manual.setdefault(key, {
                "production_order_id": int(production_order_id),
                "item_id": item_id,
                "item_sku": normalized_sku or normalized_name,
                "item_name": normalized_name,
                "unit": unit,
                "quantity": 0.0,
            })
            grouped["quantity"] += float(quantity or 0)

    for grouped in grouped_manual.values():
        production_order_id = int(grouped["production_order_id"])
        item_id = int(grouped["item_id"])
        unit = str(grouped["unit"])
        quantity = float(grouped["quantity"])
        if item_id > 0:
            key = (production_order_id, item_id, unit)
            issued_by_item_unit[key] = issued_by_item_unit.get(key, 0.0) + quantity
            continue
        for value in (grouped["item_sku"], grouped["item_name"]):
            label_key = _accessory_match_key(value)
            if not label_key:
                continue
            key = (production_order_id, label_key, unit)
            manual_by_label_unit[key] = manual_by_label_unit.get(key, 0.0) + quantity

    return issued_by_item_unit, manual_by_label_unit


def _accessory_request_rows(
    db: Session,
    *,
    production_order_id: int | None,
    model_id: int | None,
    q: str | None = None,
    candidate_offset: int | None = None,
    candidate_limit: int | None = None,
    include_candidate_count: bool = False,
) -> list[dict] | tuple[list[dict], int]:
    order_query = db.query(
        ProductionOrder.id,
        ProductionOrder.production_no,
        SalesOrder.order_no.label("sales_order_no"),
        ProductionOrder.model_id,
        ProductionOrder.planned_quantity,
    ).outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
    if production_order_id is not None:
        order_query = order_query.filter(ProductionOrder.id == production_order_id)
    else:
        order_query = order_query.filter(
            ProductionOrder.status.notin_(("finished_storage", "cancelled", "rejected"))
        )
    if model_id is not None:
        order_query = order_query.filter(ProductionOrder.model_id == model_id)
    # Search is applied before loading BOMs, issue totals, and stock.  Keep the
    # Python match below as the final authority (notably for public order
    # numbers), while this candidate query prevents unrelated orders from
    # expanding their derived accessory requirements.
    search = (q or "").strip()
    if search:
        pattern = f"%{search}%"
        normalized_search = normalized_model_code_key(search)
        search_clauses = [
            ProductionOrder.production_no.ilike(pattern),
            SalesOrder.order_no.ilike(pattern),
            Model.code.ilike(pattern),
            Model.name.ilike(pattern),
            Item.sku.ilike(pattern),
            Item.name.ilike(pattern),
            ModelBOM.unit.ilike(pattern),
            Item.unit.ilike(pattern),
        ]
        if normalized_search:
            escaped = normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search_clauses.insert(
                3,
                normalized_model_code_column(Model.code).ilike(f"%{escaped}%", escape="\\"),
            )
        candidate_query = (
            db.query(ProductionOrder.id)
            .outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
            .outerjoin(Model, Model.id == ProductionOrder.model_id)
            .outerjoin(ModelBOM, ModelBOM.model_id == ProductionOrder.model_id)
            .outerjoin(Item, Item.id == ModelBOM.item_id)
            .filter(
                or_(*search_clauses)
            )
        )
        if production_order_id is not None:
            candidate_query = candidate_query.filter(ProductionOrder.id == production_order_id)
        else:
            candidate_query = candidate_query.filter(
                ProductionOrder.status.notin_(
                    ("finished_storage", "cancelled", "rejected")
                )
            )
        if model_id is not None:
            candidate_query = candidate_query.filter(ProductionOrder.model_id == model_id)
        # Manual issues may be the only matching evidence (legacy labels do
        # not necessarily have a BOM/item row), so retain those candidates.
        manual_query = db.query(ManualAccessoryIssue.production_order_id).filter(
            or_(
                ManualAccessoryIssue.item_sku.ilike(pattern),
                ManualAccessoryIssue.item_name.ilike(pattern),
                ManualAccessoryIssue.unit.ilike(pattern),
            )
        )
        if production_order_id is not None:
            manual_query = manual_query.filter(
                ManualAccessoryIssue.production_order_id == production_order_id
            )
        order_query = order_query.filter(
            or_(
                ProductionOrder.id.in_(candidate_query.distinct()),
                ProductionOrder.id.in_(manual_query.distinct()),
            )
        )
    if candidate_limit is not None:
        order_query = (
            order_query.order_by(ProductionOrder.id.asc())
            .offset(max(0, int(candidate_offset or 0)))
            .limit(max(1, int(candidate_limit)))
        )
    else:
        order_query = order_query.order_by(
            ProductionOrder.created_at.desc(),
            ProductionOrder.id.desc(),
        )
    orders = order_query.all()
    candidate_count = len(orders)
    order_ids = [int(order.id) for order in orders]
    if not order_ids:
        return ([], 0) if include_candidate_count else []

    items_by_order: dict[int, list] = {}
    model_ids = {int(order.model_id) for order in orders}
    for start in range(0, len(order_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = order_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        item_rows = db.query(
            ProductionOrderItem.production_order_id,
            ProductionOrderItem.model_id,
            ProductionOrderItem.color,
            ProductionOrderItem.size,
            ProductionOrderItem.planned_quantity,
        ).filter(ProductionOrderItem.production_order_id.in_(chunk)).order_by(
            ProductionOrderItem.id.asc()
        ).all()
        for item_row in item_rows:
            items_by_order.setdefault(int(item_row.production_order_id), []).append(item_row)
            if item_row.model_id:
                model_ids.add(int(item_row.model_id))

    model_labels: dict[int, tuple[str | None, str | None]] = {}
    boms_by_model: dict[int, list] = {}
    sorted_model_ids = sorted(model_ids)
    for start in range(0, len(sorted_model_ids), _BULK_STOCK_CHUNK_SIZE):
        chunk = sorted_model_ids[start:start + _BULK_STOCK_CHUNK_SIZE]
        model_labels.update({
            int(row.id): (row.code, row.name)
            for row in db.query(Model.id, Model.code, Model.name).filter(Model.id.in_(chunk)).all()
        })
        bom_rows = (
            db.query(
                ModelBOM.id,
                ModelBOM.model_id,
                ModelBOM.item_id,
                ModelBOM.stock_batch_id,
                ModelBOM.size,
                ModelBOM.color,
                ModelBOM.quantity_per_piece,
                ModelBOM.unit,
                ModelBOM.waste_percent,
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                Item.image_url.label("item_image_url"),
                Item.category.label("item_category"),
                Item.unit.label("item_unit"),
            )
            .join(Item, Item.id == ModelBOM.item_id)
            .filter(ModelBOM.model_id.in_(chunk), Item.category.in_(ACCESSORY_CATEGORIES))
            .order_by(ModelBOM.id.asc())
            .all()
        )
        for bom_row in bom_rows:
            boms_by_model.setdefault(int(bom_row.model_id), []).append(bom_row)

    issued_by_item_unit, manual_by_label_unit = _accessory_request_issue_totals(db, order_ids)
    requirements_by_order: dict[int, list[dict]] = {}
    required_item_ids: set[int] = set()
    for order in orders:
        order_id = int(order.id)
        requirements: dict[tuple[int, str, int | None], dict] = {}
        order_items = items_by_order.get(order_id)
        planning_rows = order_items or [order]
        for planning_row in planning_rows:
            planned_quantity = int(planning_row.planned_quantity or 0)
            planning_model_id = int(planning_row.model_id or order.model_id)
            for bom in boms_by_model.get(planning_model_id, []):
                if order_items and bom.size and bom.size != planning_row.size:
                    continue
                if order_items and bom.color and bom.color != planning_row.color:
                    continue
                quantity = float(bom.quantity_per_piece or 0) * max(0, planned_quantity)
                quantity *= 1.0 + float(bom.waste_percent or 0) / 100.0
                if quantity <= 0:
                    continue
                unit = str(bom.unit or bom.item_unit or "").strip() or str(bom.item_unit or "")
                key = (int(bom.item_id), unit, int(bom.stock_batch_id) if bom.stock_batch_id else None)
                requirement = requirements.get(key)
                if not requirement:
                    requirement = {
                        "item_id": int(bom.item_id),
                        "item_sku": bom.item_sku,
                        "item_name": bom.item_name,
                        "item_image_url": bom.item_image_url,
                        "category": bom.item_category,
                        "unit": unit,
                        "required_quantity": 0.0,
                    }
                    requirements[key] = requirement
                requirement["required_quantity"] += quantity
        requirements_by_order[order_id] = sorted(
            requirements.values(),
            key=lambda row: (row["category"], row["item_sku"], row["unit"]),
        )
        required_item_ids.update(int(row["item_id"]) for row in requirements.values())

    available_by_item = available_stock_for_items(db, required_item_ids)
    rows: list[dict] = []
    for order in orders:
        order_id = int(order.id)
        model_code, model_name = model_labels.get(int(order.model_id), (None, None))
        for requirement in requirements_by_order[order_id]:
            item_id = int(requirement["item_id"])
            unit = str(requirement["unit"])
            issued = issued_by_item_unit.get((order_id, item_id, unit), 0.0)
            for value in (requirement["item_sku"], requirement["item_name"]):
                issued += manual_by_label_unit.get((order_id, _accessory_match_key(value), unit), 0.0)
            remaining = max(0.0, float(requirement["required_quantity"] or 0) - issued)
            available = float(available_by_item.get(item_id, 0.0))
            shortage = max(0.0, remaining - available)
            status = "ready" if remaining <= EPSILON else "shortage" if shortage > EPSILON else "partial"
            rows.append({
                "production_order_id": order_id,
                "production_no": order.production_no,
                "order_no": order.sales_order_no or public_production_order_no(order.production_no) or order.production_no,
                "model_id": int(order.model_id),
                "model_code": model_code,
                "model_name": model_name,
                "planned_quantity": int(order.planned_quantity or 0),
                **requirement,
                "issued_quantity": issued,
                "remaining_quantity": remaining,
                "available_quantity": available,
                "shortage": shortage,
                "status": status,
            })
    return (rows, candidate_count) if include_candidate_count else rows


def _accessory_request_row_matches(row: dict, search: str) -> bool:
    if not search:
        return True
    if model_code_contains(row.get("model_code"), search):
        return True
    fields = [
        row.get("order_no"),
        row.get("production_no"),
        row.get("model_name"),
        row.get("item_sku"),
        row.get("item_name"),
        row.get("unit"),
    ]
    return any(search in str(value or "").lower() for value in fields)


def _accessory_request_sort_key(row: dict) -> tuple[int, int, str]:
    return (
        0 if row["status"] == "shortage" else 1 if row["status"] == "partial" else 2,
        int(row["production_order_id"]),
        str(row["item_sku"]),
    )


def _filter_accessory_request_rows(
    rows: list[dict],
    *,
    include_complete: bool,
    search: str,
) -> list[dict]:
    return [
        row
        for row in rows
        if (include_complete or float(row.get("remaining_quantity") or 0) > EPSILON)
        and _accessory_request_row_matches(row, search)
    ]


_POSTGRESQL_ACCESSORY_REQUEST_SQL = """
WITH eligible_orders AS MATERIALIZED (
    SELECT
        po.id AS production_order_id,
        po.production_no,
        COALESCE(so.order_no, NULLIF(BTRIM(po.production_no), ''), po.production_no) AS order_no,
        po.model_id,
        po.planned_quantity,
        model.code AS model_code,
        model.name AS model_name
    FROM production_orders AS po
    LEFT JOIN sales_orders AS so ON so.id = po.sales_order_id
    JOIN models AS model ON model.id = po.model_id
    WHERE
        (
            (:production_order_id IS NOT NULL AND po.id = :production_order_id)
            OR (
                :production_order_id IS NULL
                AND po.status NOT IN ('finished_storage', 'cancelled', 'rejected')
            )
        )
        AND (:model_id IS NULL OR po.model_id = :model_id)
),
planning_rows AS MATERIALIZED (
    SELECT
        eligible.production_order_id,
        eligible.production_no,
        eligible.order_no,
        eligible.model_id,
        eligible.model_code,
        eligible.model_name,
        eligible.planned_quantity AS order_planned_quantity,
        item.id AS planning_position,
        item.model_id AS planning_model_id,
        item.size,
        item.color,
        item.planned_quantity,
        TRUE AS has_order_items
    FROM eligible_orders AS eligible
    JOIN production_order_items AS item
      ON item.production_order_id = eligible.production_order_id

    UNION ALL

    SELECT
        eligible.production_order_id,
        eligible.production_no,
        eligible.order_no,
        eligible.model_id,
        eligible.model_code,
        eligible.model_name,
        eligible.planned_quantity AS order_planned_quantity,
        0::bigint AS planning_position,
        eligible.model_id AS planning_model_id,
        NULL::varchar AS size,
        NULL::varchar AS color,
        eligible.planned_quantity,
        FALSE AS has_order_items
    FROM eligible_orders AS eligible
    WHERE NOT EXISTS (
        SELECT 1
        FROM production_order_items AS item
        WHERE item.production_order_id = eligible.production_order_id
    )
),
raw_requirements AS MATERIALIZED (
    SELECT
        planning.production_order_id,
        planning.production_no,
        planning.order_no,
        planning.model_id,
        planning.model_code,
        planning.model_name,
        planning.order_planned_quantity,
        planning.planning_position,
        bom.id AS bom_position,
        catalog_item.id AS item_id,
        catalog_item.sku AS item_sku,
        catalog_item.name AS item_name,
        catalog_item.image_url AS item_image_url,
        catalog_item.category,
        COALESCE(NULLIF(BTRIM(bom.unit), ''), catalog_item.unit, '') AS unit,
        bom.stock_batch_id,
        (
            bom.quantity_per_piece::double precision
            * GREATEST(planning.planned_quantity, 0)
            * (1.0 + bom.waste_percent::double precision / 100.0)
        ) AS required_quantity
    FROM planning_rows AS planning
    JOIN model_bom AS bom ON bom.model_id = planning.planning_model_id
    JOIN items AS catalog_item ON catalog_item.id = bom.item_id
    WHERE
        catalog_item.category IN ('accessory', 'packaging')
        AND (
            NOT planning.has_order_items
            OR bom.size IS NULL
            OR bom.size = planning.size
        )
        AND (
            NOT planning.has_order_items
            OR bom.color IS NULL
            OR bom.color = planning.color
        )
        AND (
            bom.quantity_per_piece::double precision
            * GREATEST(planning.planned_quantity, 0)
            * (1.0 + bom.waste_percent::double precision / 100.0)
        ) > 0
),
requirements AS MATERIALIZED (
    SELECT
        production_order_id,
        production_no,
        order_no,
        model_id,
        model_code,
        model_name,
        order_planned_quantity,
        item_id,
        item_sku,
        item_name,
        item_image_url,
        category,
        unit,
        stock_batch_id,
        MIN(ARRAY[planning_position::bigint, bom_position::bigint]) AS source_position,
        SUM(required_quantity) AS required_quantity
    FROM raw_requirements
    GROUP BY
        production_order_id,
        production_no,
        order_no,
        model_id,
        model_code,
        model_name,
        order_planned_quantity,
        item_id,
        item_sku,
        item_name,
        item_image_url,
        category,
        unit,
        stock_batch_id
),
required_items AS MATERIALIZED (
    SELECT DISTINCT item_id FROM requirements
),
movement_references AS MATERIALIZED (
    SELECT
        eligible.production_order_id,
        reference_kind.reference_type,
        eligible.production_order_id AS reference_id
    FROM eligible_orders AS eligible
    CROSS JOIN (
        VALUES ('ProductionOrder'), ('ProductionOrderAccessoryIssue')
    ) AS reference_kind(reference_type)

    UNION ALL

    SELECT eligible.production_order_id, 'WorkOrder', work_order.id
    FROM eligible_orders AS eligible
    JOIN work_orders AS work_order
      ON work_order.production_order_id = eligible.production_order_id

    UNION ALL

    SELECT eligible.production_order_id, 'CuttingRecord', record.id
    FROM eligible_orders AS eligible
    JOIN work_orders AS work_order
      ON work_order.production_order_id = eligible.production_order_id
    JOIN cutting_records AS record ON record.work_order_id = work_order.id

    UNION ALL

    SELECT eligible.production_order_id, 'SewingRecord', record.id
    FROM eligible_orders AS eligible
    JOIN work_orders AS work_order
      ON work_order.production_order_id = eligible.production_order_id
    JOIN sewing_records AS record ON record.work_order_id = work_order.id

    UNION ALL

    SELECT eligible.production_order_id, 'PackagingRecord', record.id
    FROM eligible_orders AS eligible
    JOIN work_orders AS work_order
      ON work_order.production_order_id = eligible.production_order_id
    JOIN packaging_records AS record ON record.work_order_id = work_order.id
),
movement_issues AS MATERIALIZED (
    SELECT
        reference.production_order_id,
        movement.item_id,
        COALESCE(NULLIF(BTRIM(movement.unit), ''), catalog_item.unit, '') AS unit,
        SUM(movement.quantity) AS quantity
    FROM movement_references AS reference
    JOIN stock_movements AS movement
      ON movement.reference_type = reference.reference_type
     AND movement.reference_id = reference.reference_id
    JOIN items AS catalog_item ON catalog_item.id = movement.item_id
    WHERE
        catalog_item.category IN ('accessory', 'packaging')
        AND movement.movement_type IN ('consume', 'issue')
    GROUP BY
        reference.production_order_id,
        movement.item_id,
        COALESCE(NULLIF(BTRIM(movement.unit), ''), catalog_item.unit, '')
),
linked_manual_issues AS MATERIALIZED (
    SELECT
        manual.production_order_id,
        manual.item_id,
        COALESCE(NULLIF(BTRIM(manual.unit), ''), 'pcs') AS unit,
        SUM(manual.quantity) AS quantity
    FROM manual_accessory_issues AS manual
    JOIN eligible_orders AS eligible
      ON eligible.production_order_id = manual.production_order_id
    WHERE manual.item_id IS NOT NULL
    GROUP BY
        manual.production_order_id,
        manual.item_id,
        COALESCE(NULLIF(BTRIM(manual.unit), ''), 'pcs')
),
item_issues AS MATERIALIZED (
    SELECT production_order_id, item_id, unit, SUM(quantity) AS quantity
    FROM (
        SELECT production_order_id, item_id, unit, quantity FROM movement_issues
        UNION ALL
        SELECT production_order_id, item_id, unit, quantity FROM linked_manual_issues
    ) AS issue_source
    GROUP BY production_order_id, item_id, unit
),
itemless_manual_source AS MATERIALIZED (
    SELECT
        manual.production_order_id,
        manual.id,
        manual.created_at,
        COALESCE(NULLIF(BTRIM(manual.unit), ''), 'pcs') AS unit,
        COALESCE(NULLIF(BTRIM(manual.item_sku), ''), NULLIF(BTRIM(manual.item_name), ''), 'Manual accessory') AS item_sku,
        COALESCE(NULLIF(BTRIM(manual.item_name), ''), NULLIF(BTRIM(manual.item_sku), ''), 'Manual accessory') AS item_name,
        REGEXP_REPLACE(
            LOWER(BTRIM(COALESCE(NULLIF(BTRIM(manual.item_sku), ''), NULLIF(BTRIM(manual.item_name), ''), 'Manual accessory'))),
            '\\s+', ' ', 'g'
        ) AS group_key,
        manual.quantity
    FROM manual_accessory_issues AS manual
    JOIN eligible_orders AS eligible
      ON eligible.production_order_id = manual.production_order_id
    WHERE manual.item_id IS NULL
),
itemless_manual_grouped AS MATERIALIZED (
    SELECT
        production_order_id,
        unit,
        group_key,
        (ARRAY_AGG(item_sku ORDER BY created_at DESC, id DESC))[1] AS item_sku,
        (ARRAY_AGG(item_name ORDER BY created_at DESC, id DESC))[1] AS item_name,
        SUM(quantity) AS quantity
    FROM itemless_manual_source
    GROUP BY production_order_id, unit, group_key
),
manual_alias_contributions AS MATERIALIZED (
    SELECT
        production_order_id,
        unit,
        REGEXP_REPLACE(LOWER(BTRIM(COALESCE(item_sku, ''))), '\\s+', ' ', 'g') AS match_key,
        quantity
    FROM itemless_manual_grouped

    UNION ALL

    SELECT
        production_order_id,
        unit,
        REGEXP_REPLACE(LOWER(BTRIM(COALESCE(item_name, ''))), '\\s+', ' ', 'g') AS match_key,
        quantity
    FROM itemless_manual_grouped
),
requirement_aliases AS MATERIALIZED (
    SELECT
        production_order_id,
        item_id,
        unit,
        stock_batch_id,
        REGEXP_REPLACE(LOWER(BTRIM(COALESCE(item_sku, ''))), '\\s+', ' ', 'g') AS match_key
    FROM requirements

    UNION ALL

    SELECT
        production_order_id,
        item_id,
        unit,
        stock_batch_id,
        REGEXP_REPLACE(LOWER(BTRIM(COALESCE(item_name, ''))), '\\s+', ' ', 'g') AS match_key
    FROM requirements
),
manual_alias_issues AS MATERIALIZED (
    SELECT
        requirement.production_order_id,
        requirement.item_id,
        requirement.unit,
        requirement.stock_batch_id,
        SUM(manual.quantity) AS quantity
    FROM requirement_aliases AS requirement
    JOIN manual_alias_contributions AS manual
      ON manual.production_order_id = requirement.production_order_id
     AND manual.unit = requirement.unit
     AND manual.match_key = requirement.match_key
    WHERE requirement.match_key <> ''
    GROUP BY
        requirement.production_order_id,
        requirement.item_id,
        requirement.unit,
        requirement.stock_batch_id
),
batch_stock AS MATERIALIZED (
    SELECT batch.item_id, SUM(batch.quantity) AS quantity
    FROM stock_batches AS batch
    JOIN required_items AS required ON required.item_id = batch.item_id
    GROUP BY batch.item_id
),
batchless_stock AS MATERIALIZED (
    SELECT
        movement.item_id,
        SUM(CASE
            WHEN movement.movement_type IN ('produce', 'return', 'adjustment') THEN movement.quantity
            ELSE 0
        END) AS incoming,
        SUM(CASE
            WHEN movement.movement_type IN ('issue', 'consume', 'waste', 'shipment') THEN movement.quantity
            ELSE 0
        END) AS outgoing
    FROM stock_movements AS movement
    JOIN required_items AS required ON required.item_id = movement.item_id
    WHERE movement.batch_id IS NULL
    GROUP BY movement.item_id
),
active_reservations AS MATERIALIZED (
    SELECT
        reservation.item_id,
        GREATEST(
            0,
            SUM(
                reservation.reserved_quantity
                - reservation.consumed_quantity
                - reservation.released_quantity
            )
        ) AS quantity
    FROM material_reservations AS reservation
    JOIN required_items AS required ON required.item_id = reservation.item_id
    WHERE reservation.status IN ('reserved', 'partially_consumed')
    GROUP BY reservation.item_id
),
quantities AS MATERIALIZED (
    SELECT
        requirement.production_order_id,
        requirement.production_no,
        requirement.order_no,
        requirement.model_id,
        requirement.model_code,
        requirement.model_name,
        requirement.order_planned_quantity AS planned_quantity,
        requirement.item_id,
        requirement.item_sku,
        requirement.item_name,
        requirement.item_image_url,
        requirement.category,
        requirement.unit,
        requirement.stock_batch_id,
        requirement.source_position,
        requirement.required_quantity,
        COALESCE(item_issue.quantity, 0) + COALESCE(alias_issue.quantity, 0) AS issued_quantity,
        GREATEST(
            0,
            requirement.required_quantity
            - COALESCE(item_issue.quantity, 0)
            - COALESCE(alias_issue.quantity, 0)
        ) AS remaining_quantity,
        (
            COALESCE(batch.quantity, 0)
            + COALESCE(batchless.incoming, 0)
            - COALESCE(batchless.outgoing, 0)
            - COALESCE(reserved.quantity, 0)
        ) AS available_quantity
    FROM requirements AS requirement
    LEFT JOIN item_issues AS item_issue
      ON item_issue.production_order_id = requirement.production_order_id
     AND item_issue.item_id = requirement.item_id
     AND item_issue.unit = requirement.unit
    LEFT JOIN manual_alias_issues AS alias_issue
      ON alias_issue.production_order_id = requirement.production_order_id
     AND alias_issue.item_id = requirement.item_id
     AND alias_issue.unit = requirement.unit
     AND alias_issue.stock_batch_id IS NOT DISTINCT FROM requirement.stock_batch_id
    LEFT JOIN batch_stock AS batch ON batch.item_id = requirement.item_id
    LEFT JOIN batchless_stock AS batchless ON batchless.item_id = requirement.item_id
    LEFT JOIN active_reservations AS reserved ON reserved.item_id = requirement.item_id
),
classified AS MATERIALIZED (
    SELECT
        quantities.*,
        GREATEST(0, remaining_quantity - available_quantity) AS shortage,
        CASE
            WHEN remaining_quantity <= 0.000000001 THEN 'ready'
            WHEN GREATEST(0, remaining_quantity - available_quantity) > 0.000000001 THEN 'shortage'
            ELSE 'partial'
        END AS status
    FROM quantities
),
filtered AS MATERIALIZED (
    SELECT *
    FROM classified
    WHERE
        (:include_complete OR remaining_quantity > 0.000000001)
        AND (
            :search = ''
            OR POSITION(:search IN LOWER(COALESCE(order_no, ''))) > 0
            OR POSITION(:search IN LOWER(COALESCE(production_no, ''))) > 0
            OR POSITION(:search IN LOWER(COALESCE(model_name, ''))) > 0
            OR POSITION(:search IN LOWER(COALESCE(item_sku, ''))) > 0
            OR POSITION(:search IN LOWER(COALESCE(item_name, ''))) > 0
            OR POSITION(:search IN LOWER(COALESCE(unit, ''))) > 0
            OR (
                :normalized_search <> ''
                AND POSITION(
                    :normalized_search IN REPLACE(
                        TRANSLATE(
                            REGEXP_REPLACE(LOWER(BTRIM(COALESCE(model_code, ''))), '\\s+', ' ', 'g'),
                            'авекмнорстху',
                            'abekmhopctxy'
                        ),
                        '-',
                        ''
                    )
                ) > 0
            )
        )
),
page_rows AS MATERIALIZED (
    SELECT *
    FROM filtered
    ORDER BY
        CASE status WHEN 'shortage' THEN 0 WHEN 'partial' THEN 1 ELSE 2 END,
        production_order_id,
        item_sku COLLATE "C",
        category COLLATE "C",
        unit COLLATE "C",
        source_position
    LIMIT :page_size OFFSET :offset
),
totals AS (
    SELECT COUNT(*)::bigint AS total FROM filtered
)
SELECT
    page.production_order_id,
    page.production_no,
    page.order_no,
    page.model_id,
    page.model_code,
    page.model_name,
    page.planned_quantity,
    page.item_id,
    page.item_sku,
    page.item_name,
    page.item_image_url,
    page.category,
    page.unit,
    page.required_quantity,
    page.issued_quantity,
    page.remaining_quantity,
    page.available_quantity,
    page.shortage,
    page.status,
    totals.total
FROM totals
LEFT JOIN page_rows AS page ON TRUE
ORDER BY
    CASE page.status WHEN 'shortage' THEN 0 WHEN 'partial' THEN 1 ELSE 2 END,
    page.production_order_id,
    page.item_sku COLLATE "C",
    page.category COLLATE "C",
    page.unit COLLATE "C",
    page.source_position
"""


def _postgresql_accessory_issue_requests(
    db: Session,
    *,
    production_order_id: int | None,
    model_id: int | None,
    q: str | None,
    include_complete: bool,
    offset: int,
    page_size: int,
) -> tuple[list[dict], int]:
    search = (q or "").strip().lower()
    result = db.execute(
        text(_POSTGRESQL_ACCESSORY_REQUEST_SQL),
        {
            "production_order_id": production_order_id,
            "model_id": model_id,
            "include_complete": include_complete,
            "search": search,
            "normalized_search": normalized_model_code_key(search),
            "offset": offset,
            "page_size": page_size,
        },
    ).mappings().all()
    total = int(result[0]["total"] or 0) if result else 0
    rows: list[dict] = []
    for raw in result:
        if raw["production_order_id"] is None:
            continue
        rows.append({
            "production_order_id": int(raw["production_order_id"]),
            "production_no": raw["production_no"],
            "order_no": raw["order_no"],
            "model_id": int(raw["model_id"]),
            "model_code": raw["model_code"],
            "model_name": raw["model_name"],
            "planned_quantity": int(raw["planned_quantity"] or 0),
            "item_id": int(raw["item_id"]),
            "item_sku": raw["item_sku"],
            "item_name": raw["item_name"],
            "item_image_url": raw["item_image_url"],
            "category": raw["category"],
            "unit": raw["unit"],
            "required_quantity": float(raw["required_quantity"] or 0),
            "issued_quantity": float(raw["issued_quantity"] or 0),
            "remaining_quantity": float(raw["remaining_quantity"] or 0),
            "available_quantity": float(raw["available_quantity"] or 0),
            "shortage": float(raw["shortage"] or 0),
            "status": raw["status"],
        })
    return rows, total


def accessory_issue_requests(
    db: Session,
    *,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    include_complete: bool = False,
    page: int | None = None,
    page_size: int | None = None,
    include_total: bool = False,
) -> list[dict] | tuple[list[dict], int]:
    search = (q or "").strip().lower()
    if page is None and page_size is None:
        rows = _accessory_request_rows(
            db,
            production_order_id=production_order_id,
            model_id=model_id,
            q=q,
        )
        filtered_rows = _filter_accessory_request_rows(
            rows,
            include_complete=include_complete,
            search=search,
        )
        filtered_rows.sort(key=_accessory_request_sort_key)
        return (filtered_rows, len(filtered_rows)) if include_total else filtered_rows

    safe_page, safe_size, offset = clamp_pagination(page or 1, page_size or 50)
    if db.get_bind().dialect.name == "postgresql":
        # Rows and the exact total intentionally come from one statement so
        # they share a PostgreSQL snapshot. SQL failures must propagate; the
        # legacy path is a dialect fallback, not an error fallback.
        rows, total = _postgresql_accessory_issue_requests(
            db,
            production_order_id=production_order_id,
            model_id=model_id,
            q=q,
            include_complete=include_complete,
            offset=offset,
            page_size=safe_size,
        )
        return (rows, total) if include_total else rows

    retained_limit = offset + safe_size
    candidate_offset = 0
    total = 0
    retained: list[dict] = []
    # Exact totals and derived status ordering require inspecting every
    # candidate. Page candidates in SQL and retain only the requested prefix
    # so queue memory stays bounded without changing the public row contract.
    while True:
        chunk_rows, candidate_count = _accessory_request_rows(
            db,
            production_order_id=production_order_id,
            model_id=model_id,
            q=q,
            candidate_offset=candidate_offset,
            candidate_limit=_BULK_STOCK_CHUNK_SIZE,
            include_candidate_count=True,
        )
        if candidate_count == 0:
            break
        filtered_chunk = _filter_accessory_request_rows(
            chunk_rows,
            include_complete=include_complete,
            search=search,
        )
        total += len(filtered_chunk)
        retained.extend(filtered_chunk)
        retained.sort(key=_accessory_request_sort_key)
        if len(retained) > retained_limit:
            del retained[retained_limit:]
        candidate_offset += candidate_count
        if candidate_count < _BULK_STOCK_CHUNK_SIZE:
            break

    page_rows = retained[offset: offset + safe_size]
    return (page_rows, total) if include_total else page_rows


def sync_sewing_accessory_block(db: Session, production_order_id: int) -> dict:
    plan = accessory_issue_plan(db, production_order_id)
    upstream_output = float(
        db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0))
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .scalar()
        or 0
    ) + float(
        db.query(func.coalesce(func.sum(PrintingRecord.passed_qty), 0))
        .join(WorkOrder, WorkOrder.id == PrintingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .scalar()
        or 0
    )
    plan["sewing_gate_active"] = upstream_output > EPSILON
    sewing_orders = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "sewing",
            WorkOrder.status.notin_(("completed", "cancelled", "rejected")),
        )
        .all()
    )
    if upstream_output <= EPSILON or plan.get("is_complete"):
        for wo in sewing_orders:
            if wo.block_reason == ACCESSORY_SEWING_BLOCK_REASON:
                wo.is_blocked = False
                wo.block_reason = None
    else:
        for wo in sewing_orders:
            wo.is_blocked = True
            wo.block_reason = ACCESSORY_SEWING_BLOCK_REASON
    db.flush()
    return plan


def missing_accessory_issue_for_sewing(db: Session, production_order_id: int) -> bool:
    plan = sync_sewing_accessory_block(db, production_order_id)
    return not bool(plan.get("is_complete"))


def ensure_accessories_issued_for_sewing(db: Session, production_order_id: int) -> dict:
    plan = sync_sewing_accessory_block(db, production_order_id)
    if plan.get("sewing_gate_active") and not plan.get("is_complete"):
        summary = plan.get("summary") or {}
        remaining = float(summary.get("remaining_quantity") or 0)
        shortage = float(summary.get("shortage") or 0)
        raise HTTPException(
            409,
            f"Accessories must be issued before sewing. Remaining {remaining:g}; shortage {shortage:g}.",
        )
    return plan


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
        quantity = Decimal(str(raw.get("quantity") or 0))
        if quantity <= 0:
            continue

        item = db.get(Item, item_id) if item_id else None
        manual = bool(raw.get("manual")) or item_id <= 0
        if manual:
            unit = str(raw.get("unit") or (item.unit if item else "") or "pcs").strip() or "pcs"
            item_sku = str(raw.get("item_sku") or (item.sku if item else "") or "").strip()
            item_name = str(raw.get("item_name") or (item.name if item else "") or item_sku).strip()
            if not item_name:
                raise HTTPException(400, "Manual accessory name is required")
            issue = ManualAccessoryIssue(
                production_order_id=po.id,
                item_id=item.id if item else None,
                item_sku=item_sku or None,
                item_name=item_name,
                quantity=quantity,
                unit=unit,
                notes=str(raw.get("notes") or "").strip() or None,
                created_by=user_id,
            )
            db.add(issue)
            issued.append({
                "item_id": int(item.id) if item else 0,
                "item_sku": item_sku or item_name,
                "item_name": item_name,
                "item_image_url": item.image_url if item else None,
                "quantity": float(quantity),
                "unit": unit,
            })
            continue

        quantity = float(quantity)

        item = db.get(Item, item_id)
        if not item or item.category not in ACCESSORY_CATEGORIES:
            raise HTTPException(400, f"Item #{item_id} is not an accessory item")

        plan_row = plan_by_item_id.get(item_id)
        if plan_row:
            remaining = float(plan_row.get("remaining_quantity") or 0)
            if quantity > remaining + 1e-9:
                raise HTTPException(
                    409,
                    f"Issue quantity for {plan_row['item_sku']} exceeds remaining accessory requirement",
                )

        available = available_stock_for_item(db, int(item.id))
        if quantity > available + 1e-9:
            raise HTTPException(
                409,
                f"Insufficient available stock for {item.sku}: available {available:g}, requested {quantity:g}",
            )

        unit = str(raw.get("unit") or (plan_row or {}).get("unit") or item.unit or "").strip() or item.unit
        if unit != item.unit:
            raise HTTPException(409, "Accessory issue unit must match the item unit")
        consumed = consume_item_from_batches(
            db,
            item_id=item.id,
            quantity=quantity,
            unit=unit,
            reference_type="ProductionOrder",
            reference_id=po.id,
            user_id=user_id,
            require_available=True,
            item_cache={int(item.id): item},
        )
        issued.append({
            "item_id": int(item.id),
            "item_sku": item.sku,
            "item_name": item.name,
            "item_image_url": item.image_url,
            "quantity": consumed,
            "unit": unit,
        })

    if not issued:
        raise HTTPException(400, "No accessory issue quantities provided")
    sync_sewing_accessory_block(db, production_order_id)

    return {
        "production_order_id": int(po.id),
        "production_no": po.production_no,
        "order_no": po.order_no,
        "issued": issued,
    }
