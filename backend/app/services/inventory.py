from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, lazyload

from app.core.pagination import clamp_pagination
from app.core.model_search import model_code_contains
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
    SewingRecord,
    StockBatch,
    StockMovement,
    SystemSetting,
    Warehouse,
    WorkOrder,
)
from app.services.numbering import next_material_reservation_no
from app.services.workflow import consume_item_from_batches, consume_stock_batch, notify_department

MATERIAL_CATEGORIES = ("fabric", "semi_finished")
ACCESSORY_CATEGORIES = ("accessory", "packaging")
RESERVABLE_CATEGORIES = MATERIAL_CATEGORIES + ACCESSORY_CATEGORIES
ACTIVE_RESERVATION_STATUSES = ("reserved", "partially_consumed")
RESERVATION_STATUSES = ("reserved", "partially_consumed", "consumed", "released", "cancelled")
RESERVATION_TYPES = ("material", "accessory", "packaging")
RESERVATION_SOURCES = ("manual", "auto_bom", "planning")
REQUIRE_RESERVATION_SETTING = "require_material_reservation_before_cutting"
ACCESSORY_SEWING_BLOCK_REASON = "Accessories must be issued before sewing."
EPSILON = 1e-9


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


def current_stock_for_batch(db: Session, stock_batch_id: int) -> float:
    batch = db.get(StockBatch, stock_batch_id)
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    return float(batch.quantity or 0)


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
        db.query(ProductionOrderItem)
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
        for planned in explicit_materials:
            stock_batch = db.get(StockBatch, planned.stock_batch_id)
            item = db.get(Item, stock_batch.item_id) if stock_batch else None
            if not stock_batch or not item:
                continue
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


def reservation_plan_for_production_order(db: Session, production_order_id: int) -> dict:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    model_code, model_name = _model_label_fields(db, po.model_id)
    coverage = _reservation_coverage_by_item_unit(db, int(po.id))
    batch_coverage = _reservation_coverage_by_item_unit_batch(db, int(po.id))
    rows = []
    for row in _bom_requirement_rows(db, po, RESERVABLE_CATEGORIES):
        stock_batch_id = int(row["stock_batch_id"]) if row.get("stock_batch_id") else None
        if stock_batch_id is not None:
            coverage_key = (int(row["item_id"]), str(row["unit"]), stock_batch_id)
            already_reserved = float(batch_coverage.get(coverage_key, 0.0))
        else:
            coverage_key = (int(row["item_id"]), str(row["unit"]))
            already_reserved = float(coverage.get(coverage_key, 0.0))
        required = float(row["required_quantity"] or 0)
        remaining = max(0.0, required - already_reserved)
        if stock_batch_id is not None:
            current = current_stock_for_batch(db, stock_batch_id)
            available = available_stock_for_batch(db, stock_batch_id)
        else:
            current = current_stock_for_item(db, int(row["item_id"]))
            available = available_stock_for_item(db, int(row["item_id"]))
        shortage = max(0.0, remaining - max(0.0, available))
        suggested_batches = _suggest_batches_for_requirement(
            db,
            item_id=int(row["item_id"]),
            unit=str(row["unit"]),
            quantity=remaining,
            stock_batch_id=stock_batch_id,
        )
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
            "reserved_stock": reserved_stock_for_batch(db, stock_batch_id) if stock_batch_id is not None else reserved_stock_for_item(db, int(row["item_id"])),
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


def _lock_batch_query(db: Session, stock_batch_id: int):
    qry = db.query(StockBatch).filter(StockBatch.id == stock_batch_id)
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
    return qry


def create_material_reservations(
    db: Session,
    *,
    production_order_id: int,
    lines: list[dict],
    user_id: int | None,
    source: str = "manual",
) -> list[MaterialReservation]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    if source not in RESERVATION_SOURCES:
        raise HTTPException(400, "Invalid reservation source")
    if not lines:
        raise HTTPException(400, "No reservation lines provided")

    created: list[MaterialReservation] = []
    for idx, raw in enumerate(lines, start=1):
        item_id = int(raw.get("item_id") or 0)
        quantity = float(raw.get("reserved_quantity") or raw.get("quantity") or 0)
        unit = str(raw.get("unit") or "").strip()
        stock_batch_id = int(raw["stock_batch_id"]) if raw.get("stock_batch_id") else None
        warehouse_id = int(raw["warehouse_id"]) if raw.get("warehouse_id") else None
        notes = str(raw.get("notes") or "").strip() or None
        if quantity <= 0:
            raise HTTPException(400, f"Reservation line #{idx} quantity must be greater than zero")
        item = db.get(Item, item_id)
        if not item:
            raise HTTPException(404, f"Item #{item_id} not found")
        if item.category not in RESERVABLE_CATEGORIES:
            raise HTTPException(400, f"Item {item.sku} is not a reservable material/accessory item")
        unit = unit or item.unit
        reservation_type = str(raw.get("reservation_type") or _reservation_type_for_category(item.category)).strip()
        if reservation_type not in RESERVATION_TYPES:
            raise HTTPException(400, "Invalid reservation_type")

        if stock_batch_id is not None:
            batch = _lock_batch_query(db, stock_batch_id).first()
            if not batch:
                raise HTTPException(404, f"Stock batch #{stock_batch_id} not found")
            if int(batch.item_id) != int(item_id):
                raise HTTPException(400, f"Batch {batch.batch_no} does not belong to item {item.sku}")
            if str(batch.unit or "").strip() != unit:
                raise HTTPException(400, f"Batch {batch.batch_no} unit is {batch.unit}, not {unit}")
            if warehouse_id is not None and int(batch.warehouse_id) != warehouse_id:
                raise HTTPException(400, f"Batch {batch.batch_no} is not in warehouse #{warehouse_id}")
            warehouse_id = int(batch.warehouse_id)
            available = available_stock_for_batch(db, int(batch.id))
            if quantity > available + EPSILON:
                raise HTTPException(
                    409,
                    f"Cannot reserve {quantity:g} {unit} from batch {batch.batch_no}; available unreserved quantity is {available:g}",
                )
        else:
            if warehouse_id is not None and not db.get(Warehouse, warehouse_id):
                raise HTTPException(404, f"Warehouse #{warehouse_id} not found")
            available = available_stock_for_item(db, item_id, warehouse_id=warehouse_id)
            if quantity > available + EPSILON:
                raise HTTPException(
                    409,
                    f"Cannot reserve {quantity:g} {unit} for item {item.sku}; available unreserved quantity is {available:g}",
                )

        reservation = MaterialReservation(
            reservation_no=next_material_reservation_no(db),
            production_order_id=int(po.id),
            sales_order_id=int(po.sales_order_id) if po.sales_order_id else None,
            item_id=item_id,
            stock_batch_id=stock_batch_id,
            warehouse_id=warehouse_id,
            reserved_quantity=quantity,
            consumed_quantity=0,
            released_quantity=0,
            unit=unit,
            status="reserved",
            reservation_type=reservation_type,
            source=source,
            reserved_by=user_id,
            reserved_at=datetime.now(timezone.utc),
            notes=notes,
        )
        db.add(reservation)
        db.flush()
        created.append(reservation)
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


def release_material_reservation(db: Session, reservation_id: int) -> MaterialReservation:
    reservation = db.get(MaterialReservation, reservation_id)
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
    reservation = db.get(MaterialReservation, reservation_id)
    if not reservation:
        raise HTTPException(404, "Material reservation not found")
    if reservation.status not in ACTIVE_RESERVATION_STATUSES:
        raise HTTPException(409, f"Reservation is not active (status: {reservation.status})")
    quantity = float(quantity or 0)
    if quantity <= 0:
        raise HTTPException(400, "Consume quantity must be greater than zero")
    remaining = _open_reservation_quantity(reservation)
    if quantity > remaining + EPSILON:
        raise HTTPException(409, f"Consume quantity exceeds remaining reserved quantity ({remaining:g})")

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
        )

    reservation.consumed_quantity = float(reservation.consumed_quantity or 0) + quantity
    _set_reservation_status(reservation)
    db.flush()
    return reservation


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

    qry = (
        db.query(MaterialReservation)
        .filter(
            MaterialReservation.production_order_id == production_order_id,
            MaterialReservation.stock_batch_id == stock_batch_id,
            MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
        )
        .order_by(MaterialReservation.created_at.asc(), MaterialReservation.id.asc())
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        qry = qry.options(
            lazyload(MaterialReservation.item),
            lazyload(MaterialReservation.stock_batch),
            lazyload(MaterialReservation.warehouse),
        ).with_for_update(of=MaterialReservation)
    reservations = qry.all()

    reserved_available = sum(_open_reservation_quantity(row) for row in reservations)
    if require_full and reserved_available + EPSILON < quantity:
        raise HTTPException(
            409,
            f"Insufficient material reservation for cutting: reserved {reserved_available:g}, requested {quantity:g} "
            "for this production order and fabric batch.",
        )

    left = quantity
    consumed = 0.0
    for reservation in reservations:
        if left <= EPSILON:
            break
        take = min(left, _open_reservation_quantity(reservation))
        if take <= EPSILON:
            continue
        consume_material_reservation(
            db,
            int(reservation.id),
            quantity=take,
            user_id=user_id,
            reference_type=reference_type,
            reference_id=reference_id,
        )
        consumed += take
        left -= take

    return consumed


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


def accessory_issue_summary(
    db: Session,
    *,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
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
    if page is not None or page_size is not None:
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
    if page is not None or page_size is not None:
        safe_page, safe_size, _ = clamp_pagination(page or 1, page_size or 50)
        manual_query = manual_query.limit(max(safe_page * safe_size * 20, safe_size))
    manual_issues = manual_query.all()

    all_po_ids = set(po_ids_by_movement_id.values()) | {
        int(issue.production_order_id) for issue in manual_issues if issue.production_order_id
    }
    if not all_po_ids:
        return []
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
        key = (int(po.id), item_id, unit, _accessory_match_key(item_sku or item_name))
        model = model_by_id.get(int(po.model_id))
        first_at = issue.created_at
        last_at = issue.created_at
        existing = grouped.get(key)  # type: ignore[arg-type]
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
            grouped[key] = existing  # type: ignore[index]
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
    if page is not None or page_size is not None:
        safe_page, safe_size, offset = clamp_pagination(page or 1, page_size or 50)
        return sorted_rows[offset: offset + safe_size]
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

    rows = []
    for row in required_rows:
        key = (int(row["item_id"]), str(row["unit"]))
        issued = issued_by_item_unit.get(key, 0.0)
        unit = str(row["unit"])
        for value in (row.get("item_sku"), row.get("item_name")):
            manual_key = (_accessory_match_key(value), unit)
            issued += manual_issued_by_label_unit.get(manual_key, 0.0)
        available = available_stock_for_item(db, int(row["item_id"]))
        remaining = max(0.0, float(row["required_quantity"] or 0) - issued)
        shortage = max(0.0, remaining - available)
        if remaining <= EPSILON:
            status = "ready"
        elif shortage > EPSILON:
            status = "shortage"
        else:
            status = "partial"
        rows.append({
            **row,
            "issued_quantity": issued,
            "remaining_quantity": remaining,
            "available_quantity": available,
            "shortage": shortage,
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


def accessory_issue_requests(
    db: Session,
    *,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    include_complete: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> list[dict]:
    qry = db.query(ProductionOrder)
    if production_order_id is not None:
        qry = qry.filter(ProductionOrder.id == production_order_id)
    else:
        qry = qry.filter(ProductionOrder.status.notin_(("finished_storage", "cancelled", "rejected")))
    if model_id is not None:
        qry = qry.filter(ProductionOrder.model_id == model_id)
    qry = qry.order_by(ProductionOrder.created_at.desc(), ProductionOrder.id.desc())
    production_orders = qry.all()

    rows: list[dict] = []
    for po in production_orders:
        plan = accessory_issue_plan(db, int(po.id))
        for row in plan["rows"]:
            remaining = float(row.get("remaining_quantity") or 0)
            if not include_complete and remaining <= EPSILON:
                continue
            rows.append({
                "production_order_id": int(po.id),
                "production_no": po.production_no,
                "order_no": po.order_no,
                "model_id": int(po.model_id),
                "model_code": plan.get("model_code"),
                "model_name": plan.get("model_name"),
                "planned_quantity": int(po.planned_quantity or 0),
                "item_id": int(row["item_id"]),
                "item_sku": row["item_sku"],
                "item_name": row["item_name"],
                "item_image_url": row.get("item_image_url"),
                "category": row["category"],
                "unit": row["unit"],
                "required_quantity": float(row.get("required_quantity") or 0),
                "issued_quantity": float(row.get("issued_quantity") or 0),
                "remaining_quantity": remaining,
                "available_quantity": float(row.get("available_quantity") or 0),
                "shortage": float(row.get("shortage") or 0),
                "status": row["status"],
            })

    search = (q or "").strip().lower()
    if search:
        def matches(row: dict) -> bool:
            fields = [
                row.get("order_no"),
                row.get("production_no"),
                row.get("model_code"),
                row.get("model_name"),
                row.get("item_sku"),
                row.get("item_name"),
                row.get("unit"),
            ]
            return any(search in str(value or "").lower() for value in fields)

        rows = [row for row in rows if matches(row)]

    rows.sort(
        key=lambda row: (
            0 if row["status"] == "shortage" else 1 if row["status"] == "partial" else 2,
            row["production_order_id"],
            row["item_sku"],
        )
    )
    if page is not None or page_size is not None:
        safe_page, safe_size, offset = clamp_pagination(page or 1, page_size or 50)
        return rows[offset: offset + safe_size]
    return rows


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
        quantity = float(raw.get("quantity") or 0)
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
                "quantity": quantity,
                "unit": unit,
            })
            continue

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
