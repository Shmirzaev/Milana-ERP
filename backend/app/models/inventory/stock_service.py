"""Inventory stock: master data, warehouses, receipts, adjustments and batches.

User-facing write operations own their outer transaction. The public
``record_purchase_order_stock_receipt`` participant is the exception: Purchasing
owns that cross-domain transaction and passes its Session. Stock truth
(available/reserved quantities) stays in ``app.models.inventory_service``; this
module never recomputes it.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, lazyload

from app.core.costs import round_unit_cost
from app.core.deps import is_admin, user_permissions
from app.core.dt import date_filter_bounds
from app.core.order_reference import (
    canonical_business_order_reference,
    canonical_order_reference,
    order_reference_contains,
)
from app.core.pagination import clamp_pagination
from app.libs.dto.inventory.accessory_issue_input import AccessoryIssueIn
from app.libs.dto.inventory.accessory_issue_output import (
    AccessoryIssueRequestRow, AccessoryIssueSummaryRow,
)
from app.libs.dto.inventory.accessory_return_input import AccessoryReturnIn
from app.libs.dto.inventory.item_input import ItemIn
from app.libs.dto.inventory.item_output import ItemOut
from app.libs.dto.inventory.stock_batch_input import StockBatchIn
from app.libs.dto.inventory.stock_batch_output import StockBatchOut
from app.libs.dto.inventory.stock_batch_restore_input import StockBatchRestoreIn
from app.libs.dto.inventory.stock_batch_roll_weights_input import StockBatchRollWeightsIn
from app.libs.dto.inventory.stock_batch_update import StockBatchUpdate
from app.libs.dto.inventory.stock_line_output import StockLine
from app.libs.dto.inventory.stock_quantity_adjustment_input import StockQuantityAdjustmentIn
from app.libs.dto.inventory.stock_quantity_adjustment_output import StockQuantityAdjustmentOut
from app.libs.dto.inventory.warehouse_input import WarehouseIn
from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.libs.types.inventory import (
    ItemInsertCommand,
    PurchaseOrderStockReceiptCommand,
    PurchaseOrderStockReceiptResult,
    StockBatchEditCommand,
    StockBatchEditValues,
)
from app.models import inventory_access_service as inventory_access
from app.models.catalog import models_service as catalog_models_service
from app.models.audit_service import log_action
from app.models.idempotency_service import replay_idempotent_response, store_idempotent_response
from app.models.inventory_service import (
    accessory_issue_plan,
    accessory_issue_requests,
    accessory_issue_summary,
    available_stock_for_batch,
    categories_for_group,
    current_stock_for_item,
    issue_accessories_to_production_order,
    release_material_reservation,
    reserved_stock_for_batch,
    reserved_stock_for_item,
    stock_summary,
)
from app.models.material_rolls_service import normalize_material_roll_lengths, normalize_material_roll_weights
from app.models.workflow_service import archive_depleted_material_batch
from app.schemas import (
    CuttingMaterialUsage,
    CuttingRecord,
    Item,
    MaterialReservation,
    ModelBOM,
    ProductionOrder,
    ProductionOrderMaterial,
    PurchaseOrderLine,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
    Supplier,
    User,
    Warehouse,
    WasteRecord,
)
from app.schemas.inventory import item_persistence
from app.schemas.inventory import stock_movement_persistence
from app.schemas.inventory import stock_receipt_persistence
from app.schemas.inventory import stock_batch_persistence
from app.schemas.inventory import warehouse_persistence
from app.schemas.inventory.eco_transfer import EcoFabricRoll

EPSILON = 1e-9
_STOCK_BATCH_QC_STATUSES = frozenset(status.value for status in StockBatchQcStatus)


def _validate_receiving_warehouse(item: Item, warehouse: Warehouse) -> None:
    material_categories = categories_for_group("materials") or ()
    accessory_categories = categories_for_group("accessories") or ()
    expected_type = None
    expected_name = None
    if item.category in material_categories:
        expected_type = "fabric_storage"
        expected_name = "Fabric Storage"
    elif item.category in accessory_categories:
        expected_type = "accessory_storage"
        expected_name = "Accessory Storage"
    if expected_type and warehouse.type != expected_type:
        raise HTTPException(400, f"{item.name} must be received into {expected_name}")


def _normalize_stock_batch_qc_status(value: StockBatchQcStatus | None) -> StockBatchQcStatus:
    """Unwrap the validated update member at the existing string storage boundary.

    The DTO owns normalization and membership validation. Explicit null still
    reaches this service refusal; an omitted field never calls this helper.
    """
    if value is None:
        raise HTTPException(400, "Invalid QC status")
    return value


def _require_admin_force(current: User, force: bool) -> None:
    if force and not (is_admin(current) or "inventory.force_override" in user_permissions(current)):
        raise HTTPException(403, "Missing permission: inventory.force_override")


def _locked_stock_batch_statement(batch_id: int):
    # StockBatch.item is joined eagerly by default. PostgreSQL rejects a broad
    # FOR UPDATE when that optional eager relationship adds an outer join, so
    # lock only the stock_batches query and load no relationship for mutation.
    return (
        select(StockBatch)
        .options(lazyload(StockBatch.item))
        .where(StockBatch.id == batch_id, StockBatch.archived_at.is_(None))
        .with_for_update()
    )


def _locked_active_batch_reservations_statement(batch_id: int):
    # MaterialReservation relationships are joined eagerly by default. Locking
    # that generated outer-join query is rejected by PostgreSQL, so suppress
    # relationship loading and lock only the reservation table rows.
    return (
        select(MaterialReservation)
        .options(lazyload("*"))
        .where(
            MaterialReservation.stock_batch_id == batch_id,
            MaterialReservation.status.in_(("reserved", "partially_consumed")),
        )
        .with_for_update(of=MaterialReservation)
    )


def _delete_stock_batch_receipt_movements(db, movements: list[StockMovement]) -> None:
    for movement in movements:
        db.delete(movement)
    # StockBatch has no ORM relationship to StockMovement, so SQLAlchemy cannot
    # infer the FK delete order. Flush child deletions before deleting the batch.
    db.flush()


def _validate_item_image_url(image_url: str | None) -> str | None:
    if not image_url:
        return None
    value = image_url.strip()
    if not value:
        return None
    lowered = value.lower()
    if lowered.startswith(("javascript:", "data:", "vbscript:", "file:")):
        raise HTTPException(400, "Unsupported image URL")
    if value.startswith("/storage/model-files/") or value.startswith(("https://", "http://")):
        return value
    raise HTTPException(400, "Image URL must be an uploaded file path or an http(s) URL")


def _item_payload(payload: ItemIn) -> dict:
    data = payload.model_dump()
    data["default_cost"] = round_unit_cost(data["default_cost"])
    data["name"] = str(data.get("name") or "").strip()
    data["image_url"] = _validate_item_image_url(data.get("image_url"))
    composition = []
    total_pct = 0.0
    for row in data.pop("composition", []) or []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        percentage = float(row.get("percentage") or 0)
        composition.append({"name": name, "percentage": percentage})
        total_pct += percentage
    if total_pct > 100.0001:
        raise HTTPException(400, "Composition total cannot exceed 100%")
    data["composition_json"] = composition
    return data


def _item_name_group_categories(category: str) -> tuple[str, ...]:
    material_categories = categories_for_group("materials") or ()
    accessory_categories = categories_for_group("accessories") or ()
    if category in material_categories:
        return material_categories
    if category in accessory_categories:
        return accessory_categories
    return (category,)


def _ensure_unique_active_item_name(db, data: dict, item_id: int | None = None) -> None:
    if not data.get("is_active", True):
        return
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Item name is required")
    categories = _item_name_group_categories(str(data.get("category") or ""))
    qry = db.query(Item.id).filter(
        Item.is_active.is_(True),
        Item.category.in_(categories),
        func.lower(func.trim(Item.name)) == name.lower(),
    )
    if item_id is not None:
        qry = qry.filter(Item.id != item_id)
    if qry.first():
        label = "Material" if categories == (categories_for_group("materials") or ()) else "Item"
        raise HTTPException(400, f"{label} name already exists")


# ===== Items =====
def list_items(
    db,
    user: User,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    group = inventory_access.scoped_group(user, group, category)
    qry = db.query(Item).filter(Item.is_active.is_(True))
    categories = categories_for_group(group)
    if categories:
        qry = qry.filter(Item.category.in_(categories))
    if category: qry = qry.filter(Item.category == category)
    if q: qry = qry.filter((Item.name.ilike(f"%{q}%")) | (Item.sku.ilike(f"%{q}%")))
    start, end = date_filter_bounds(created_from, created_to)
    if start: qry = qry.filter(Item.created_at >= start)
    if end: qry = qry.filter(Item.created_at <= end)
    safe_page, safe_size, offset = clamp_pagination(page, page_size)
    total = qry.count() if include_total else 0
    qry = qry.order_by(Item.id.desc())
    qry = qry.offset(offset).limit(safe_size)
    rows = [ItemOut.model_validate(row).model_dump() for row in qry.all()]
    if include_total:
        return {"rows": rows, "total": total, "page": safe_page, "page_size": safe_size}
    return rows


def update_item_image(db, item_id: int, payload, current: User) -> Item:
    inventory_access.require_item(db, current, item_id)
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    old_value = {"image_url": it.image_url}
    it.image_url = _validate_item_image_url(payload.image_url)
    log_action(db, current, "update_image", "Item", it.id, old_value=old_value, new_value={"image_url": it.image_url})
    db.commit(); db.refresh(it)
    return it


def create_item(db, payload: ItemIn, current: User) -> Item:
    inventory_access.require_category(current, payload.category)
    if db.query(Item).filter(Item.sku == payload.sku).first():
        raise HTTPException(400, "SKU already exists")
    data = _item_payload(payload)
    _ensure_unique_active_item_name(db, data)
    command = ItemInsertCommand(
        sku=data["sku"], name=data["name"], category=data["category"], unit=data["unit"],
        default_cost=data["default_cost"], reorder_level=data["reorder_level"],
        track_batch=data["track_batch"], is_active=data["is_active"],
        image_url=data["image_url"], composition_json=data["composition_json"],
    )
    it = item_persistence.insert_item(db, command)
    log_action(db, current, "create", "Item", it.id, new_value={"sku": it.sku})
    db.commit(); db.refresh(it)
    return it


def update_item(db, item_id: int, payload: ItemIn, current: User) -> Item:
    inventory_access.require_item(db, current, item_id)
    inventory_access.require_category(current, payload.category)
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    duplicate = db.query(Item).filter(Item.sku == payload.sku, Item.id != item_id).first()
    if duplicate:
        raise HTTPException(400, "SKU already exists")
    data = _item_payload(payload)
    _ensure_unique_active_item_name(db, data, item_id=item_id)
    old_value = {
        "sku": it.sku,
        "name": it.name,
        "category": it.category,
        "unit": it.unit,
        "is_active": it.is_active,
    }
    for k, v in data.items():
        setattr(it, k, v)
    log_action(db, current, "update", "Item", it.id, old_value=old_value, new_value={"sku": it.sku, "name": it.name})
    db.commit(); db.refresh(it)
    return it


def delete_item(db, item_id: int, current: User, force: bool = False) -> bool:
    """Delete an item, or archive it when linked records exist and force is set.

    Returns True when the item was archived instead of deleted.
    """
    inventory_access.require_item(db, current, item_id)
    _require_admin_force(current, force)
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    linked = (
        db.query(StockBatch.id).filter(StockBatch.item_id == item_id).first()
        or db.query(StockMovement.id).filter(StockMovement.item_id == item_id).first()
        or db.query(ModelBOM.id).filter(ModelBOM.item_id == item_id).first()
        or db.query(PurchaseRequestLine.id).filter(PurchaseRequestLine.item_id == item_id).first()
        or db.query(PurchaseOrderLine.id).filter(PurchaseOrderLine.item_id == item_id).first()
        or db.query(WasteRecord.id).filter(WasteRecord.item_id == item_id).first()
    )
    if linked and not force:
        raise HTTPException(409, "Item is linked to stock, BOM, purchasing, or waste records")
    if linked:
        old_value = {"sku": it.sku, "name": it.name, "is_active": it.is_active}
        it.is_active = False
        log_action(
            db,
            current,
            "force_archive",
            "Item",
            item_id,
            old_value=old_value,
            new_value={"is_active": False, "linked_records_preserved": True},
        )
        db.commit()
        return True
    db.delete(it)
    log_action(db, current, "delete", "Item", item_id, new_value={"sku": it.sku, "name": it.name})
    db.commit()
    return False


# ===== Warehouses =====
def list_warehouses(db, user: User) -> list[Warehouse]:
    qry = db.query(Warehouse)
    if inventory_access.materials_only(user):
        qry = qry.filter(Warehouse.type != "accessory_storage")
    return qry.order_by(Warehouse.id).all()


def create_warehouse(db: Session, payload: WarehouseIn, current: User) -> Warehouse:
    w = warehouse_persistence.insert_warehouse(
        db, name=payload.name, type=payload.type, department_id=payload.department_id,
    )
    log_action(db, current, "create", "Warehouse", w.id)
    db.commit(); db.refresh(w)
    return w


# ===== Stock adjustment =====
def _stock_adjustment_warehouse_id(db, item: Item, batches: list[StockBatch]) -> int:
    if batches:
        return int(batches[0].warehouse_id)
    preferred_types = ("fabric_storage", "raw_material", "warehouse")
    if item.category in {"accessory", "packaging"}:
        preferred_types = ("accessory_storage", "warehouse", "fabric_storage")
    for warehouse_type in preferred_types:
        warehouse = db.query(Warehouse).filter(Warehouse.type == warehouse_type).order_by(Warehouse.id).first()
        if warehouse:
            return int(warehouse.id)
    warehouse = db.query(Warehouse).order_by(Warehouse.id).first()
    if not warehouse:
        raise HTTPException(400, "Create a warehouse before setting batch-tracked stock")
    return int(warehouse.id)


def _unique_adjustment_batch_no(db, item: Item) -> str:
    base = f"{item.sku}-ADJ-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    candidate = base
    suffix = 1
    while db.query(StockBatch.id).filter(StockBatch.batch_no == candidate).first():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _apply_batch_tracked_stock_adjustment(
    db,
    *,
    item: Item,
    delta: float,
    movement_type: StockMovementType,
    user_id: int | None,
) -> list[StockMovement]:
    if abs(delta) <= EPSILON:
        return []
    batches_query = (
        db.query(StockBatch)
        .filter(
            StockBatch.item_id == item.id,
            StockBatch.unit == item.unit,
            StockBatch.archived_at.is_(None),
        )
        .order_by(StockBatch.id.desc())
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        batches_query = batches_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
    batches = batches_query.populate_existing().all()
    movements: list[StockMovement] = []
    if delta > 0:
        batch = batches[0] if batches else None
        if not batch:
            batch = stock_movement_persistence.add_adjustment_batch(
                db,
                item_id=int(item.id),
                batch_no=_unique_adjustment_batch_no(db, item),
                quantity=0,
                unit=item.unit,
                cost_per_unit=round_unit_cost(item.default_cost or 0),
                warehouse_id=_stock_adjustment_warehouse_id(db, item, batches),
                qc_status=StockBatchQcStatus.PASSED,
            )
        stock_movement_persistence.set_batch_quantity(
            db, batch, float(batch.quantity or 0) + delta
        )
        movement = stock_movement_persistence.add_stock_adjustment_movement(
            db,
            movement_type=movement_type,
            item_id=int(item.id),
            batch_id=int(batch.id),
            from_warehouse_id=None,
            to_warehouse_id=int(batch.warehouse_id),
            quantity=delta,
            unit=item.unit,
            created_by=user_id,
        )
        movements.append(movement)
        return movements

    left = abs(delta)
    for batch in batches:
        if left <= EPSILON:
            break
        available = float(batch.quantity or 0)
        if available <= EPSILON:
            continue
        qty = min(available, left)
        stock_movement_persistence.set_batch_quantity(db, batch, available - qty)
        movement = stock_movement_persistence.add_stock_adjustment_movement(
            db,
            movement_type=movement_type,
            item_id=int(item.id),
            batch_id=int(batch.id),
            from_warehouse_id=int(batch.warehouse_id),
            to_warehouse_id=None,
            quantity=qty,
            unit=item.unit,
            created_by=user_id,
        )
        archive_depleted_material_batch(db, batch, user_id=user_id)
        movements.append(movement)
        left -= qty
    if left > EPSILON:
        raise HTTPException(409, f"Batch stock cannot be reduced by {abs(delta):g} {item.unit}; only {abs(delta) - left:g} is in batches")
    return movements


def set_stock_quantity(
    db,
    item_id: int,
    payload: StockQuantityAdjustmentIn,
    current: User,
    force: bool = False,
) -> StockQuantityAdjustmentOut:
    inventory_access.require_item(db, current, item_id)
    _require_admin_force(current, force)
    # Serialize item-wide adjustments, including items with no batch rows yet.
    item_query = db.query(Item).filter(Item.id == item_id)
    if db.bind and db.bind.dialect.name == "postgresql":
        item_query = item_query.with_for_update(of=Item)
    item = item_query.populate_existing().first()
    if not item:
        raise HTTPException(404, "Item not found")
    # Lock batches before reading the total, using the reservation lock pattern.
    batches_query = db.query(StockBatch).filter(StockBatch.item_id == item_id).order_by(StockBatch.id.desc())
    if db.bind and db.bind.dialect.name == "postgresql":
        batches_query = batches_query.options(lazyload(StockBatch.item)).with_for_update(of=StockBatch)
    batches_query.populate_existing().all()
    unit = (payload.unit or item.unit or "").strip()
    if not unit:
        raise HTTPException(400, "Unit is required")
    if unit != item.unit:
        raise HTTPException(400, f"Stock unit must match item unit ({item.unit})")
    target_quantity = float(payload.quantity or 0)
    previous_quantity = current_stock_for_item(db, item_id)
    reserved_quantity = reserved_stock_for_item(db, item_id)
    # Force permits legacy batch selection behavior, but a correction must
    # never leave active reservations backed by less physical stock.
    if target_quantity + EPSILON < reserved_quantity:
        raise HTTPException(409, f"Stock quantity cannot be lower than reserved quantity ({reserved_quantity:g} {item.unit})")
    delta = target_quantity - previous_quantity
    if abs(delta) <= EPSILON:
        return StockQuantityAdjustmentOut(
            item_id=item_id,
            previous_quantity=previous_quantity,
            quantity=previous_quantity,
            delta=0,
            unit=item.unit,
        )

    movement_type = StockMovementType.ADJUSTMENT if delta > 0 else StockMovementType.ISSUE
    if item.track_batch:
        active_batch_count = (
            db.query(StockBatch.id)
            .filter(
                StockBatch.item_id == item.id,
                StockBatch.unit == item.unit,
                StockBatch.quantity > EPSILON,
            )
            .limit(2)
            .count()
        )
        if active_batch_count > 1 and not force:
            raise HTTPException(409, "Batch-tracked stock has multiple active batches; adjust a specific batch instead")
        movements = _apply_batch_tracked_stock_adjustment(
            db,
            item=item,
            delta=delta,
            movement_type=movement_type,
            user_id=current.id,
        )
        movement = movements[0] if movements else None
    else:
        movement = stock_movement_persistence.add_stock_adjustment_movement(
            db,
            movement_type=movement_type,
            item_id=item_id,
            batch_id=None,
            from_warehouse_id=None,
            to_warehouse_id=None,
            quantity=abs(delta),
            unit=item.unit,
            created_by=current.id,
        )
    db.flush()
    log_action(
        db,
        current,
        "stock_adjustment",
        "Item",
        item.id,
        old_value={"item_id": item_id, "quantity": previous_quantity, "unit": item.unit},
        new_value={"item_id": item_id, "quantity": target_quantity, "delta": delta, "unit": item.unit},
    )
    db.commit()
    if movement:
        db.refresh(movement)
    return StockQuantityAdjustmentOut(
        item_id=item_id,
        previous_quantity=previous_quantity,
        quantity=target_quantity,
        delta=delta,
        unit=item.unit,
        movement_id=movement.id if movement else None,
        movement_type=movement_type,
    )


def list_received_stock_colors(db, user: User) -> list[str]:
    rows = (
        db.query(StockBatch.color)
        .filter(StockBatch.item_id.in_(db.query(Item.id).filter(Item.category.in_(inventory_access.MATERIAL_CATEGORIES))) if inventory_access.materials_only(user) else True)
        .filter(
            StockBatch.color.isnot(None),
            func.length(func.trim(StockBatch.color)) > 0,
        )
        .distinct()
        .all()
    )
    colors_by_key: dict[str, str] = {}
    for (raw_color,) in rows:
        color = str(raw_color or "").strip()
        if color:
            colors_by_key.setdefault(color.casefold(), color)
    return sorted(colors_by_key.values(), key=str.casefold)


# ===== Stock view =====
def stock_view(
    db,
    user: User,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    """One page of the stock view, scoped to the caller's inventory group."""
    group = inventory_access.scoped_group(user, group, category)
    safe_page, safe_size, _ = clamp_pagination(page, page_size)
    start, end = date_filter_bounds(created_from, created_to)
    summary = stock_summary(
        db,
        category,
        group,
        q,
        supplier_id=supplier_id,
        created_from=start,
        created_to=end,
        page=safe_page,
        page_size=safe_size,
        include_total=include_total,
    )
    if include_total:
        rows, total = summary
    else:
        rows = summary
        total = 0
    # adapt -> StockLine
    out = []
    for r in rows:
        out.append(StockLine(
            item_id=r["item_id"],
            item_sku=r["sku"],
            item_name=r["name"],
            item_image_url=r.get("image_url"),
            warehouse_id=0,
            quantity=r["quantity"],
            unit=r["unit"],
            reserved_quantity=r.get("reserved_quantity", 0),
            available_quantity=r.get("available_quantity", r["quantity"]),
        ).model_dump())
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out


# ===== Receive =====
def _canonical_stock_replay(db: Session, replay: dict, *, production_order_id: int | None = None) -> dict:
    # Preserve the recorded result and request hash; only render known aliases live.
    response = dict(replay)
    if "order_no" in response:
        if production_order_id is not None:
            response["order_no"] = canonical_order_reference(
                db, "SO", response["order_no"], production_order_id=production_order_id,
            )
        else:
            response["order_no"] = canonical_business_order_reference(db, response["order_no"])
    if "internal_batch_no" in response:
        response["internal_batch_no"] = canonical_order_reference(db, "PUR", response["internal_batch_no"])
    return response


def _stock_batch_fingerprint_payload(payload: StockBatchIn) -> dict:
    """The idempotency fingerprint payload of a stock batch request.

    `qc_status` is hashed as the client sent it, not as the normalized member.
    The recorded hashes were created while the field was a free-form string, so
    a retry of such a request has to reproduce its recorded representation.
    The request contract still exposes the canonical value on the wire.
    """
    fingerprint_payload = payload.model_dump(mode="json")
    raw_qc_status = payload.raw_qc_status
    fingerprint_payload["qc_status"] = raw_qc_status if raw_qc_status is not None else payload.qc_status.value
    if payload.length_m is None:
        fingerprint_payload.pop("length_m", None)
    if not payload.roll_lengths_m:
        fingerprint_payload.pop("roll_lengths_m", None)
    return fingerprint_payload


def record_purchase_order_stock_receipt(
    db: Session,
    *,
    command: PurchaseOrderStockReceiptCommand,
) -> PurchaseOrderStockReceiptResult:
    """Write Inventory's batch and movement for a validated Purchasing receipt.

    Purchasing owns the checks, audit, idempotency and outer transaction. This
    public same-Session participant only delegates the stock-owned mappings and
    preserves the receipt's batch flush for its generated identifier.
    """
    batch = stock_receipt_persistence.add_stock_batch(
        db,
        item_id=command.item_id,
        batch_no=command.batch_no,
        internal_batch_no=command.internal_batch_no,
        supplier_id=command.supplier_id,
        color=command.color,
        old_code=command.old_code,
        color_code=command.color_code,
        color_status=command.color_status,
        order_no=command.order_no,
        width=command.width,
        gsm=command.gsm,
        quantity=command.quantity,
        piece_count=command.piece_count,
        roll_weights_kg=command.roll_weights_kg,
        processes=command.processes,
        unit=command.unit,
        cost_per_unit=command.cost_per_unit,
        image_url=command.image_url,
        warehouse_id=command.warehouse_id,
        qc_status=command.qc_status,
    )
    stock_receipt_persistence.add_receive_movement(
        db,
        item_id=command.item_id,
        batch_id=batch.id,
        to_warehouse_id=command.warehouse_id,
        quantity=command.quantity,
        unit=command.unit,
        reference_type="PurchaseOrderLine",
        reference_id=command.purchase_order_line_id,
        created_by=command.created_by,
    )
    return PurchaseOrderStockReceiptResult(
        batch_id=int(batch.id),
        batch_no=batch.batch_no,
        internal_batch_no=batch.internal_batch_no,
    )


def receive_stock(
    db: Session,
    payload: StockBatchIn,
    current: User,
    idempotency_key: str | None = None,
) -> StockBatchOut:
    inventory_access.require_item(db, current, payload.item_id)
    fingerprint_payload = _stock_batch_fingerprint_payload(payload)
    replay = replay_idempotent_response(db, scope="inventory.receive", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return StockBatchOut.model_validate(_canonical_stock_replay(db, replay))

    item = db.get(Item, payload.item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if not warehouse:
        raise HTTPException(404, "Warehouse not found")
    _validate_receiving_warehouse(item, warehouse)
    cost_per_unit = round_unit_cost(payload.cost_per_unit)
    order_no = canonical_business_order_reference(db, payload.order_no)
    roll_weights, piece_count = normalize_material_roll_weights(
        item_category=item.category,
        unit=payload.unit,
        quantity=payload.quantity,
        roll_weights_kg=payload.roll_weights_kg,
        piece_count=payload.piece_count,
    )
    roll_lengths_m = normalize_material_roll_lengths(
        item_category=item.category, roll_lengths_m=payload.roll_lengths_m, piece_count=piece_count,
    )
    image_url = _validate_item_image_url(payload.image_url)
    # The request contract already carries a canonical QC member; the schema
    # operation converts it to the stored string at the column boundary.
    qc_status = payload.qc_status
    batch = stock_receipt_persistence.add_stock_batch(
        db,
        item_id=payload.item_id,
        batch_no=payload.batch_no,
        supplier_id=payload.supplier_id,
        color=payload.color,
        old_code=payload.old_code,
        color_code=payload.color_code,
        color_status=payload.color_status,
        order_no=order_no,
        width=payload.width,
        gsm=payload.gsm,
        length_m=payload.length_m,
        quantity=payload.quantity,
        piece_count=piece_count,
        roll_weights_kg=roll_weights,
        roll_lengths_m=roll_lengths_m,
        processes=payload.processes,
        unit=payload.unit,
        cost_per_unit=cost_per_unit,
        image_url=image_url,
        warehouse_id=payload.warehouse_id,
        qc_status=qc_status,
    )
    stock_receipt_persistence.add_receive_movement(
        db,
        item_id=payload.item_id,
        batch_id=batch.id,
        to_warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        unit=payload.unit,
        reference_type="StockBatch",
        reference_id=batch.id,
        created_by=current.id,
    )
    log_action(db, current, "receive", "StockBatch", batch.id, new_value={"batch_no": batch.batch_no, "qty": float(batch.quantity)})
    db.flush()
    db.refresh(batch)
    response = StockBatchOut.model_validate(batch)
    store_idempotent_response(
        db,
        scope="inventory.receive",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response.model_dump(mode="json"),
        user=current,
        status_code=201,
    )
    db.commit()
    return response


# ===== Accessory returns and issues =====
def _lock_accessory_return_allowance(db, production_order_id: int) -> None:
    """Serialize the shared issue allowance behind an accessory return.

    `returnable_quantity` is an aggregate, not a row: it is the order's issued
    movements plus its manual accessory issues, minus every return already
    recorded against the order. No single row carries it, so the production
    order is the narrowest row that scopes all of it, and locking it is what
    makes the read and the return the request records one decision.

    `key_share=True` renders FOR NO KEY UPDATE, the narrowest row lock that
    still serializes the read. A blanket FOR UPDATE would also conflict with the
    FOR KEY SHARE PostgreSQL takes for the production_order_id foreign key that
    reservation, work-order and movement writers insert under, so a return would
    block those writers against this order row for no added safety.

    The lock is a no-op when the order does not exist, so the route keeps its
    own 404, and PostgreSQL releases it on commit or rollback.
    """
    if db.bind and db.bind.dialect.name == "postgresql":
        (
            db.query(ProductionOrder)
            .filter(ProductionOrder.id == production_order_id)
            .populate_existing()
            .with_for_update(of=ProductionOrder, key_share=True)
            .first()
        )


def collect_back_accessory(
    db,
    payload: AccessoryReturnIn,
    current: User,
    idempotency_key: str | None = None,
) -> dict:
    inventory_access.require_accessories(current)
    # The allowance read below must not race the return this request records.
    _lock_accessory_return_allowance(db, payload.production_order_id)
    fingerprint_payload = _stock_batch_fingerprint_payload(payload)
    replay = replay_idempotent_response(db, scope="inventory.accessory-return", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return _canonical_stock_replay(db, replay, production_order_id=payload.production_order_id)

    if payload.quantity <= 0:
        raise HTTPException(400, "Return quantity must be greater than zero")
    po = db.get(ProductionOrder, payload.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    item = db.get(Item, payload.item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    accessory_categories = categories_for_group("accessories") or ()
    if item.category not in accessory_categories:
        raise HTTPException(400, "Only accessory or packaging items can be collected back here")
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if not warehouse:
        raise HTTPException(404, "Warehouse not found")
    _validate_receiving_warehouse(item, warehouse)

    unit = str(payload.unit or item.unit or "").strip() or item.unit
    issued_rows = accessory_issue_summary(db, production_order_id=int(po.id))
    issued_row = next(
        (
            row for row in issued_rows
            if int(row["item_id"]) == int(item.id) and str(row["unit"] or "").strip() == unit
        ),
        None,
    )
    if not issued_row:
        raise HTTPException(400, "This accessory was not issued for the selected production order")
    returnable = float(issued_row.get("returnable_quantity") or 0)
    if payload.quantity > returnable + EPSILON:
        raise HTTPException(
            409,
            f"Cannot collect back {payload.quantity:g} {unit}; returnable issued quantity is {returnable:g}",
        )

    batch_data = payload.model_dump(exclude={"production_order_id", "return_condition"})
    batch_data["qc_status"] = payload.qc_status.value
    batch_data["cost_per_unit"] = round_unit_cost(batch_data["cost_per_unit"])
    batch_data["roll_lengths_m"] = normalize_material_roll_lengths(
        item_category=item.category, roll_lengths_m=payload.roll_lengths_m, piece_count=payload.piece_count,
    )
    batch_data["image_url"] = _validate_item_image_url(batch_data.get("image_url"))
    batch_data["unit"] = unit
    batch_data["order_no"] = po.order_no or po.production_no
    condition = str(payload.return_condition or "").strip()
    process_note = str(batch_data.get("processes") or "").strip()
    batch_data["processes"] = "; ".join(
        part for part in [f"Accessory condition: {condition}" if condition else "", process_note] if part
    ) or None

    batch = StockBatch(**batch_data)
    db.add(batch)
    db.flush()
    mv = StockMovement(
        movement_type="return",
        item_id=int(item.id),
        batch_id=batch.id,
        to_warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        unit=unit,
        reference_type="ProductionOrderAccessoryReturn",
        reference_id=int(po.id),
        created_by=current.id,
    )
    db.add(mv)
    log_action(
        db,
        current,
        "return_accessory",
        "StockBatch",
        batch.id,
        new_value={
            "production_order_id": int(po.id),
            "batch_no": batch.batch_no,
            "item_id": int(item.id),
            "qty": float(batch.quantity),
        },
    )
    db.flush()
    db.refresh(batch)
    response = StockBatchOut.model_validate(batch).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="inventory.accessory-return",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    return response


def issue_accessories(db, payload: AccessoryIssueIn, current: User) -> dict:
    inventory_access.require_accessories(current)
    result = issue_accessories_to_production_order(
        db,
        production_order_id=payload.production_order_id,
        lines=[line.model_dump() for line in payload.lines],
        user_id=current.id,
    )
    log_action(
        db,
        current,
        "issue_accessories",
        "ProductionOrder",
        payload.production_order_id,
        new_value={"issued": result["issued"], "notes": payload.notes},
    )
    db.commit()
    return result


def accessory_issue_plan_view(db, user: User, production_order_id: int) -> dict:
    """The accessory issue plan for one production order."""
    inventory_access.require_accessories(user)
    return accessory_issue_plan(db, production_order_id)


def list_accessory_issue_summary(
    db,
    user: User,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    """The issued-accessory summary rows, one page."""
    inventory_access.require_accessories(user)
    safe_page, safe_size, _ = clamp_pagination(page, page_size)
    rows = accessory_issue_summary(
        db,
        production_order_id=production_order_id,
        model_id=model_id,
        q=q,
        page=safe_page,
        page_size=safe_size,
    )
    total = len(rows)
    if include_total:
        return {
            "rows": [AccessoryIssueSummaryRow(**row).model_dump() for row in rows],
            "total": total,
            "page": safe_page,
            "page_size": safe_size,
        }
    return [AccessoryIssueSummaryRow(**row).model_dump() for row in rows]


def list_accessory_issue_request_rows(
    db,
    user: User,
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    include_complete: bool = False,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    """The outstanding accessory request rows, one page."""
    inventory_access.require_accessories(user)
    safe_page, safe_size, _ = clamp_pagination(page, page_size)
    result = accessory_issue_requests(
        db,
        production_order_id=production_order_id,
        model_id=model_id,
        q=q,
        include_complete=include_complete,
        page=safe_page,
        page_size=safe_size,
        include_total=include_total,
    )
    if include_total:
        all_rows, total = result
        return {
            "rows": [AccessoryIssueRequestRow(**row).model_dump() for row in all_rows],
            "total": total,
            "page": safe_page,
            "page_size": safe_size,
        }
    return [AccessoryIssueRequestRow(**row).model_dump() for row in result]


# ===== Batches =====
def save_batch_roll_weights(db, batch_id: int, payload: StockBatchRollWeightsIn, current: User) -> StockBatch:
    inventory_access.require_batch(db, current, batch_id)
    batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=batch_id).with_for_update().first()
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    if db.query(EcoFabricRoll.id).filter_by(batch_id=batch_id, returned_at=None).first():
        raise HTTPException(409, "Return outstanding fabric through the Eco Cotton register before changing this batch")
    item = db.get(Item, batch.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    old_weights = [float(value) for value in (batch.roll_weights_kg or [])]
    old_piece_count = batch.piece_count
    roll_weights, piece_count = normalize_material_roll_weights(
        item_category=item.category,
        unit=batch.unit,
        quantity=float(batch.quantity),
        roll_weights_kg=payload.roll_weights_kg,
        piece_count=None,
        require_weights=True,
    )
    if batch.roll_lengths_m and piece_count != batch.piece_count:
        raise HTTPException(409, "Cannot change roll count after individual roll lengths have been recorded")
    batch.roll_weights_kg = roll_weights
    batch.piece_count = piece_count
    log_action(
        db,
        current,
        "save_roll_weights",
        "StockBatch",
        batch.id,
        old_value={"piece_count": old_piece_count, "roll_weights_kg": old_weights},
        new_value={"piece_count": piece_count, "roll_weights_kg": roll_weights},
    )
    db.commit()
    db.refresh(batch)
    return batch


def update_batch(db, batch_id: int, payload: StockBatchUpdate, current: User, force: bool = False) -> dict:
    inventory_access.require_batch(db, current, batch_id)
    inventory_access.require_item(db, current, payload.item_id)
    _require_admin_force(current, force)
    batch = db.query(StockBatch).options(lazyload(StockBatch.item)).filter_by(id=batch_id).with_for_update().first()
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    if db.query(EcoFabricRoll.id).filter_by(batch_id=batch_id, returned_at=None).first():
        raise HTTPException(409, "Return outstanding fabric through the Eco Cotton register before changing this batch")
    item = db.get(Item, batch.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    values = payload.model_dump(exclude_unset=True)
    if not values:
        return batch

    if "order_no" in values:
        values["order_no"] = canonical_business_order_reference(db, values["order_no"])

    old_warehouse_id = int(batch.warehouse_id)
    old_quantity = float(batch.quantity or 0)
    old_unit = str(batch.unit or "")
    reserved_quantity = reserved_stock_for_batch(db, batch_id)

    if "batch_no" in values:
        values["batch_no"] = str(values["batch_no"] or "").strip()
        if not values["batch_no"]:
            raise HTTPException(400, "Batch number is required")
    if "quantity" in values and values["quantity"] is None:
        raise HTTPException(400, "Quantity is required")
    if "cost_per_unit" in values and values["cost_per_unit"] is None:
        raise HTTPException(400, "Cost per unit is required")
    if "cost_per_unit" in values:
        values["cost_per_unit"] = round_unit_cost(values["cost_per_unit"])
    if "received_date" in values and values["received_date"] is None:
        raise HTTPException(400, "Received date is required")
    if "unit" in values:
        values["unit"] = str(values["unit"] or "").strip()
        if not values["unit"]:
            raise HTTPException(400, "Unit is required")
        if values["unit"] != item.unit:
            raise HTTPException(409, "Batch unit must match the material unit")
        if values["unit"] != old_unit and reserved_quantity > EPSILON:
            raise HTTPException(409, "Cannot change unit while stock is reserved")
    if "warehouse_id" in values:
        if values["warehouse_id"] is None or not db.get(Warehouse, int(values["warehouse_id"])):
            raise HTTPException(404, "Warehouse not found")
        if int(values["warehouse_id"]) != old_warehouse_id and reserved_quantity > EPSILON:
            raise HTTPException(409, "Cannot change warehouse while stock is reserved")
    if "supplier_id" in values and values["supplier_id"] is not None:
        if not db.get(Supplier, int(values["supplier_id"])):
            raise HTTPException(404, "Supplier not found")
    if "qc_status" in values:
        values["qc_status"] = _normalize_stock_batch_qc_status(payload.qc_status)
    if "image_url" in values:
        values["image_url"] = _validate_item_image_url(values["image_url"])

    target_quantity = float(values.get("quantity", old_quantity))
    # Force permits linked-record overrides, but a correction must never leave
    # active reservations on this batch backed by less physical stock.
    if target_quantity + EPSILON < reserved_quantity:
        raise HTTPException(
            409,
            f"Quantity cannot be lower than reserved stock ({reserved_quantity:g} {old_unit})",
        )
    target_warehouse_id = int(values.get("warehouse_id", old_warehouse_id))
    target_unit = str(values.get("unit", old_unit))
    target_item = item
    item_movements: list[StockMovement] = []
    if "item_id" in values:
        if values["item_id"] is None:
            raise HTTPException(400, "Material is required")
        target_item = db.get(Item, int(values["item_id"]))
        if not target_item:
            raise HTTPException(404, "Material not found")
        if target_item.id != item.id and not target_item.is_active:
            raise HTTPException(409, "Selected material is inactive")
        if target_item.category not in _item_name_group_categories(item.category):
            raise HTTPException(409, "Batch material must stay in the same inventory group")
        if target_item.unit != target_unit:
            raise HTTPException(409, "Batch unit must match the selected material unit")
        values["item_id"] = int(target_item.id)
        if target_item.id != item.id:
            linked = (
                db.query(MaterialReservation.id).filter(MaterialReservation.stock_batch_id == batch_id).first()
                or db.query(ModelBOM.id).filter(ModelBOM.stock_batch_id == batch_id).first()
                or db.query(ProductionOrder.id).filter(ProductionOrder.fabric_batch_id == batch_id).first()
                or db.query(ProductionOrderMaterial.id).filter(ProductionOrderMaterial.stock_batch_id == batch_id).first()
                or db.query(CuttingRecord.id).filter(CuttingRecord.fabric_batch_id == batch_id).first()
                or db.query(CuttingMaterialUsage.id).filter(CuttingMaterialUsage.stock_batch_id == batch_id).first()
                or db.query(WasteRecord.id).filter(WasteRecord.batch_id == batch_id).first()
            )
            item_movements = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).all()
            has_downstream_movement = any(
                movement.movement_type != "receive"
                or movement.reference_type != "StockBatch"
                or int(movement.reference_id or 0) != batch_id
                for movement in item_movements
            )
            if (reserved_quantity > EPSILON or linked or has_downstream_movement) and not force:
                raise HTTPException(409, "Stock batch is already reserved or used and cannot change material")

    old_value = {
        "item_id": batch.item_id,
        "batch_no": batch.batch_no,
        "supplier_id": batch.supplier_id,
        "color": batch.color,
        "old_code": batch.old_code,
        "color_code": batch.color_code,
        "color_status": batch.color_status,
        "order_no": batch.order_no,
        "width": float(batch.width) if batch.width is not None else None,
        "length_m": float(batch.length_m) if batch.length_m is not None else None,
        "gsm": float(batch.gsm) if batch.gsm is not None else None,
        "quantity": old_quantity,
        "piece_count": batch.piece_count,
        "processes": batch.processes,
        "unit": old_unit,
        "cost_per_unit": float(batch.cost_per_unit or 0),
        "image_url": batch.image_url,
        "received_date": batch.received_date.isoformat() if batch.received_date else None,
        "warehouse_id": old_warehouse_id,
        "qc_status": batch.qc_status,
    }

    if batch.roll_lengths_m and "piece_count" in values and values["piece_count"] != batch.piece_count:
        raise HTTPException(409, "Cannot change roll count after individual roll lengths have been recorded")
    edit_values: StockBatchEditValues = {}
    if "item_id" in values:
        edit_values["item_id"] = values["item_id"]
    if "batch_no" in values:
        edit_values["batch_no"] = values["batch_no"]
    if "supplier_id" in values:
        edit_values["supplier_id"] = values["supplier_id"]
    if "color" in values:
        edit_values["color"] = values["color"]
    if "old_code" in values:
        edit_values["old_code"] = values["old_code"]
    if "color_code" in values:
        edit_values["color_code"] = values["color_code"]
    if "color_status" in values:
        edit_values["color_status"] = values["color_status"]
    if "order_no" in values:
        edit_values["order_no"] = values["order_no"]
    if "width" in values:
        edit_values["width"] = values["width"]
    if "length_m" in values:
        edit_values["length_m"] = values["length_m"]
    if "gsm" in values:
        edit_values["gsm"] = values["gsm"]
    if "quantity" in values:
        edit_values["quantity"] = values["quantity"]
    if "piece_count" in values:
        edit_values["piece_count"] = values["piece_count"]
    if "processes" in values:
        edit_values["processes"] = values["processes"]
    if "unit" in values:
        edit_values["unit"] = values["unit"]
    if "cost_per_unit" in values:
        edit_values["cost_per_unit"] = values["cost_per_unit"]
    if "image_url" in values:
        edit_values["image_url"] = values["image_url"]
    if "received_date" in values:
        edit_values["received_date"] = values["received_date"]
    if "warehouse_id" in values:
        edit_values["warehouse_id"] = values["warehouse_id"]
    if "qc_status" in values:
        edit_values["qc_status"] = values["qc_status"]
    edit_command = StockBatchEditCommand(
            values=edit_values,
            old_warehouse_id=old_warehouse_id,
            target_warehouse_id=target_warehouse_id,
            target_quantity=target_quantity,
            old_quantity=old_quantity,
            target_unit=target_unit,
            actor_id=current.id,
            relink_item_id=int(target_item.id) if target_item.id != item.id else None,
            item_movements=tuple(item_movements),
        )
    relinked_item_references = stock_batch_persistence.apply_batch_edit(db, batch, edit_command)
    if target_item.id != item.id:
        relinked_item_references["model_bom"] = catalog_models_service.relink_stock_batch_boms_for_inventory(
            db,
            stock_batch_id=batch_id,
            item_id=int(target_item.id),
        )
        relinked_item_references["waste_records"] = stock_batch_persistence.relink_batch_waste_items(
            db,
            batch_id=batch_id,
            item_id=int(target_item.id),
        )
    stock_batch_persistence.add_batch_edit_movements(db, batch, edit_command)
    if target_item.id != item.id:
        item = target_item

    archive_depleted_material_batch(db, batch, user_id=current.id)

    db.flush()
    new_value = {
        key: (
            value.value if isinstance(value, StockBatchQcStatus)
            else value.isoformat() if isinstance(value, datetime)
            else value
        )
        for key, value in values.items()
    }
    if relinked_item_references is not None:
        new_value["relinked_item_references"] = relinked_item_references
    log_action(db, current, "update", "StockBatch", batch.id, old_value=old_value, new_value=new_value)
    db.commit()
    db.refresh(batch)
    response = StockBatchOut.model_validate(batch).model_dump(mode="json")
    supplier = db.get(Supplier, batch.supplier_id) if batch.supplier_id else None
    warehouse = db.get(Warehouse, batch.warehouse_id)
    response.update({
        "item_sku": item.sku,
        "item_name": item.name,
        "item_category": item.category,
        "supplier_name": supplier.name if supplier else None,
        "warehouse_name": warehouse.name if warehouse else None,
        "reserved_quantity": reserved_stock_for_batch(db, batch.id),
        "available_quantity": available_stock_for_batch(db, batch.id),
    })
    return response


def archive_or_delete_batch(db, batch_id: int, current: User, force: bool = False) -> None:
    inventory_access.require_batch(db, current, batch_id)
    _require_admin_force(current, force)
    batch = db.execute(_locked_stock_batch_statement(batch_id)).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    if db.query(EcoFabricRoll.id).filter_by(batch_id=batch_id, returned_at=None).first():
        raise HTTPException(409, "Return outstanding fabric through the Eco Cotton register before changing this batch")

    linked = (
        db.query(EcoFabricRoll.id).filter_by(batch_id=batch_id).first()
        or
        db.query(MaterialReservation.id).filter(MaterialReservation.stock_batch_id == batch_id).first()
        or db.query(ModelBOM.id).filter(ModelBOM.stock_batch_id == batch_id).first()
        or db.query(ProductionOrder.id).filter(ProductionOrder.fabric_batch_id == batch_id).first()
        or db.query(ProductionOrderMaterial.id).filter(ProductionOrderMaterial.stock_batch_id == batch_id).first()
        or db.query(CuttingRecord.id).filter(CuttingRecord.fabric_batch_id == batch_id).first()
        or db.query(CuttingMaterialUsage.id).filter(CuttingMaterialUsage.stock_batch_id == batch_id).first()
        or db.query(WasteRecord.id).filter(WasteRecord.batch_id == batch_id).first()
    )
    movements = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).all()
    has_downstream_movement = any(
        movement.movement_type != "receive"
        or movement.reference_type != "StockBatch"
        or int(movement.reference_id or 0) != batch_id
        for movement in movements
    )

    old_value = {
        "batch_no": batch.batch_no,
        "item_id": batch.item_id,
        "quantity": float(batch.quantity or 0),
        "unit": batch.unit,
        "warehouse_id": batch.warehouse_id,
        "supplier_id": batch.supplier_id,
        "qc_status": batch.qc_status,
    }
    item = db.get(Item, int(batch.item_id))
    is_material_batch = bool(
        item and str(item.category or "").strip().lower() in {"fabric", "semi_finished"}
    )
    if is_material_batch or linked or has_downstream_movement:
        reservations = db.execute(
            _locked_active_batch_reservations_statement(batch_id)
        ).scalars().all()
        released_quantity = 0.0
        for reservation in reservations:
            remaining = max(
                0.0,
                float(reservation.reserved_quantity or 0)
                - float(reservation.consumed_quantity or 0)
                - float(reservation.released_quantity or 0),
            )
            release_material_reservation(db, int(reservation.id))
            released_quantity += remaining

        removed_quantity = float(batch.quantity or 0)
        if removed_quantity > EPSILON:
            db.add(StockMovement(
                movement_type="issue",
                item_id=batch.item_id,
                batch_id=batch.id,
                from_warehouse_id=batch.warehouse_id,
                quantity=removed_quantity,
                unit=batch.unit,
                reference_type="StockBatchDelete",
                reference_id=batch.id,
                created_by=current.id,
            ))
        batch.quantity = 0
        batch.qc_status = "hold"
        batch.archived_at = datetime.now(ZoneInfo("Asia/Tashkent"))
        batch.archived_by = current.id
        log_action(
            db,
            current,
            "archive",
            "StockBatch",
            batch_id,
            old_value=old_value,
            new_value={
                "quantity": 0,
                "qc_status": "hold",
                "removed_quantity": removed_quantity,
                "released_reservation_count": len(reservations),
                "released_reservation_quantity": released_quantity,
                "linked_records_preserved": bool(linked),
                "archive_reason": "deleted",
            },
        )
        db.commit()
        return

    _delete_stock_batch_receipt_movements(db, movements)
    db.delete(batch)
    log_action(db, current, "delete", "StockBatch", batch_id, old_value=old_value)
    db.commit()


def restore_material_batch(db, batch_id: int, payload: StockBatchRestoreIn, current: User) -> StockBatch:
    inventory_access.require_batch(db, current, batch_id)
    # Lock only the batch table; joined nullable item loads cannot be locked on PostgreSQL.
    batch = db.execute(
        select(StockBatch).options(lazyload(StockBatch.item))
        .where(StockBatch.id == batch_id).with_for_update(of=StockBatch)
    ).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    if db.query(EcoFabricRoll.id).filter_by(batch_id=batch_id, returned_at=None).first():
        raise HTTPException(409, "Return outstanding fabric through the Eco Cotton register before changing this batch")
    item = db.get(Item, batch.item_id)
    if not item or item.category not in inventory_access.MATERIAL_CATEGORIES:
        raise HTTPException(400, "Only material batches can be restored")
    if not item.is_active:
        raise HTTPException(409, "Reactivate or reassign the archived master material before restoring this batch")
    if batch.archived_at is None and float(batch.quantity) > EPSILON:
        raise HTTPException(409, "This batch is already in inventory")
    if float(batch.quantity) > EPSILON:
        raise HTTPException(409, "Archived batch has a nonzero balance; reconcile it before restoring")
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, "A restoration reason is required")
    warehouse = db.get(Warehouse, batch.warehouse_id)
    if not warehouse:
        raise HTTPException(409, "Batch warehouse no longer exists")
    _validate_receiving_warehouse(item, warehouse)
    old_value = {
        "quantity": float(batch.quantity), "archived_at": batch.archived_at,
        "archived_by": batch.archived_by, "qc_status": batch.qc_status,
        "piece_count": batch.piece_count, "roll_weights_kg": batch.roll_weights_kg, "roll_lengths_m": batch.roll_lengths_m,
    }
    # The user confirms physical stock, not a rollback of historical consumption.
    # Past receipts, usage and released/consumed reservations remain unchanged.
    batch.quantity = payload.quantity
    batch.archived_at = None
    batch.archived_by = None
    batch.qc_status = "pending"
    batch.roll_weights_kg = []
    batch.roll_lengths_m = []
    batch.piece_count = None
    db.add(StockMovement(
        movement_type="return", item_id=batch.item_id, batch_id=batch.id,
        to_warehouse_id=batch.warehouse_id, quantity=payload.quantity, unit=batch.unit,
        reference_type="StockBatchRestore", reference_id=batch.id, created_by=current.id,
    ))
    log_action(db, current, "restore", "StockBatch", batch.id, old_value=old_value, new_value={
        "quantity": float(payload.quantity), "reason": reason, "qc_status": "pending",
        "physical_stock_confirmed": True, "history_preserved": True,
    })
    db.commit()
    db.refresh(batch)
    return batch


def list_batches(
    db,
    user: User,
    item_id: int | None = None,
    item_ids: str | None = None,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    supplier_id: int | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
    hide_empty: bool = False,
    archived: bool = False,
):
    group = inventory_access.scoped_group(user, group, category)
    inventory_access.require_item(db, user, item_id)
    qry = (
        db.query(StockBatch, Item, Warehouse, Supplier)
        .join(Item, Item.id == StockBatch.item_id)
        .join(Warehouse, Warehouse.id == StockBatch.warehouse_id)
        .outerjoin(Supplier, Supplier.id == StockBatch.supplier_id)
    )
    if archived:
        # Include legacy zero-balance batches that predate automatic archiving,
        # so the archive is complete on the first release without rewriting data.
        qry = qry.filter(or_(StockBatch.archived_at.isnot(None), StockBatch.quantity <= EPSILON))
    else:
        qry = qry.filter(StockBatch.archived_at.is_(None))
    item_filter_ids: set[int] = set()
    if item_id:
        item_filter_ids.add(int(item_id))
    if item_ids:
        for raw_id in item_ids.split(","):
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            try:
                parsed_id = int(raw_id)
            except ValueError as exc:
                raise HTTPException(400, "Invalid item_ids filter") from exc
            if parsed_id > 0:
                item_filter_ids.add(parsed_id)
    if item_filter_ids:
        qry = qry.filter(StockBatch.item_id.in_(sorted(item_filter_ids)))
    categories = categories_for_group(group)
    if categories:
        qry = qry.filter(Item.category.in_(categories))
    if category:
        qry = qry.filter(Item.category == category)
    if supplier_id:
        qry = qry.filter(StockBatch.supplier_id == supplier_id)
    if hide_empty:
        qry = qry.filter(StockBatch.quantity > 0)
    search = str(q or "").strip()
    if search:
        like = f"%{search}%"
        qry = qry.filter(
            or_(
                Item.sku.ilike(like),
                Item.name.ilike(like),
                Item.unit.ilike(like),
                StockBatch.batch_no.ilike(like),
                StockBatch.internal_batch_no.ilike(like),
                StockBatch.color.ilike(like),
                StockBatch.old_code.ilike(like),
                StockBatch.color_code.ilike(like),
                StockBatch.color_status.ilike(like),
                order_reference_contains(StockBatch.order_no, like),
                StockBatch.processes.ilike(like),
                StockBatch.unit.ilike(like),
                StockBatch.qc_status.ilike(like),
                Supplier.name.ilike(like),
                Warehouse.name.ilike(like),
            )
        )
    start, end = date_filter_bounds(created_from, created_to)
    if start:
        qry = qry.filter(StockBatch.received_date >= start)
    if end:
        qry = qry.filter(StockBatch.received_date <= end)
    safe_page, safe_size, offset = clamp_pagination(page, page_size)
    unpaged_qry = qry
    if include_total:
        qry = qry.add_columns(func.count(StockBatch.id).over().label("page_total"))
    raw_rows = (
        qry.order_by(StockBatch.received_date.desc(), StockBatch.id.desc())
        .offset(offset)
        .limit(safe_size)
        .all()
    )
    if include_total:
        total = int(raw_rows[0][4] or 0) if raw_rows else 0
        if not raw_rows and safe_page > 1:
            total = unpaged_qry.count()
        rows = [tuple(row[:4]) for row in raw_rows]
    else:
        total = 0
        rows = raw_rows
    batch_ids = [int(batch.id) for batch, _, _, _ in rows]
    offsite_rolls: dict[int, list[int]] = {}
    if batch_ids:
        for bid, roll in db.query(EcoFabricRoll.batch_id, EcoFabricRoll.roll_number).filter(
            EcoFabricRoll.batch_id.in_(batch_ids), EcoFabricRoll.returned_at.is_(None)).all():
            offsite_rolls.setdefault(bid, []).append(roll)
    active_reservations: dict[int, list[dict]] = {batch_id: [] for batch_id in batch_ids}
    reserved_by_batch: dict[int, float] = {batch_id: 0.0 for batch_id in batch_ids}
    movement_summary: dict[int, dict[str, object]] = {
        batch_id: {
            "received_quantity": 0.0,
            "used_quantity": 0.0,
            "deleted": False,
            "last_archive_activity_at": None,
        }
        for batch_id in batch_ids
    }
    if batch_ids:
        reservation_rows = (
            db.query(MaterialReservation)
            .filter(
                MaterialReservation.stock_batch_id.in_(batch_ids),
                MaterialReservation.status.in_(("reserved", "partially_consumed")),
            )
            .order_by(MaterialReservation.created_at.desc(), MaterialReservation.id.desc())
            .all()
        )
        for reservation in reservation_rows:
            batch_id = int(reservation.stock_batch_id)
            raw_remaining = (
                float(reservation.reserved_quantity or 0)
                - float(reservation.consumed_quantity or 0)
                - float(reservation.released_quantity or 0)
            )
            remaining = max(
                0.0,
                raw_remaining,
            )
            reserved_by_batch[batch_id] = reserved_by_batch.get(batch_id, 0.0) + raw_remaining
            active_reservations.setdefault(batch_id, []).append({
                "id": int(reservation.id),
                "reservation_no": reservation.reservation_no,
                "production_order_id": int(reservation.production_order_id),
                "reserved_quantity": float(reservation.reserved_quantity or 0),
                "remaining_quantity": remaining,
                "unit": reservation.unit,
                "status": reservation.status,
            })
        if archived:
            movement_rows = (
                db.query(StockMovement)
                .filter(StockMovement.batch_id.in_(batch_ids))
                .order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
                .all()
            )
            for movement in movement_rows:
                batch_id = int(movement.batch_id)
                summary = movement_summary[batch_id]
                quantity = float(movement.quantity or 0)
                if movement.reference_type == "StockBatchRestore":
                    summary["deleted"] = False
                if movement.reference_type == "StockBatchDelete":
                    summary["deleted"] = True
                    summary["last_archive_activity_at"] = movement.created_at
                    continue
                if movement.movement_type in {"receive", "return", "produce"} or (
                    movement.movement_type == "adjustment"
                    and movement.to_warehouse_id is not None
                    and movement.from_warehouse_id is None
                ):
                    summary["received_quantity"] = float(summary["received_quantity"]) + quantity
                elif movement.movement_type in {"issue", "consume", "waste", "shipment"}:
                    summary["used_quantity"] = float(summary["used_quantity"]) + quantity
                    summary["last_archive_activity_at"] = movement.created_at
    out = []
    for batch, item, warehouse, supplier in rows:
        reserved_qty = max(0.0, reserved_by_batch.get(int(batch.id), 0.0))
        summary = movement_summary.get(int(batch.id), {})
        row = {
            **StockBatchOut.model_validate(batch).model_dump(),
            "offsite_roll_numbers": offsite_rolls.get(batch.id, []),
            "available_piece_count": max(0, (batch.piece_count or 0) - len(offsite_rolls.get(batch.id, []))) if batch.piece_count is not None else None,
            "item_sku": item.sku if item else None,
            "item_name": item.name if item else None,
            "item_category": item.category if item else None,
            "supplier_name": supplier.name if supplier else None,
            "warehouse_name": warehouse.name if warehouse else None,
            "reserved_quantity": reserved_qty,
            "available_quantity": float(batch.quantity or 0) - reserved_qty,
            "active_reservations": active_reservations.get(int(batch.id), []),
        }
        if archived:
            row.update({
                "item_image_url": item.image_url if item else None,
                "archived_by": batch.archived_by,
                "archived_at": (
                    batch.archived_at or summary.get("last_archive_activity_at") or batch.updated_at
                ),
                "archive_reason": "deleted" if summary.get("deleted") else "used",
                "received_quantity": float(summary.get("received_quantity") or 0),
                "used_quantity": float(summary.get("used_quantity") or 0),
            })
        out.append(row)
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out
