import os
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Depends, Header, UploadFile, File, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import lazyload

from app.core.dt import date_filter_bounds
from app.core.deps import (
    DbSession,
    INVENTORY_READ_PERMISSIONS,
    WAREHOUSE_READ_PERMISSIONS,
    PRODUCTION_READ_PERMISSIONS,
    require_permissions,
)
from app.models import (
    Item,
    CuttingRecord,
    MaterialReservation,
    ModelBOM,
    ProductionOrder,
    PurchaseOrderLine,
    PurchaseRequestLine,
    StockBatch,
    StockMovement,
    Supplier,
    User,
    Warehouse,
    WasteRecord,
)
from app.schemas.inventory import (
    ItemImageIn, ItemIn, ItemOut, WarehouseIn, WarehouseOut,
    AccessoryReturnIn, StockBatchIn, StockBatchOut, StockBatchUpdate, StockMovementIn, StockMovementOut, StockLine,
    AccessoryIssueIn, AccessoryIssueOut, AccessoryIssuePlanOut, AccessoryIssueRequestRow, AccessoryIssueSummaryRow,
    MaterialReservationAutoIn, MaterialReservationConsumeIn, MaterialReservationIn,
    MaterialReservationOut, MaterialReservationPlanOut, StockQuantityAdjustmentIn, StockQuantityAdjustmentOut,
)
from app.services.audit import log_action
from app.services.idempotency import replay_idempotent_response, store_idempotent_response
from app.services.inventory import (
    accessory_issue_plan,
    accessory_issue_requests,
    accessory_issue_summary,
    auto_reserve_materials_for_production_order,
    available_stock_for_batch,
    categories_for_group,
    consume_material_reservation,
    create_material_reservations,
    issue_accessories_to_production_order,
    material_reservation_status_for_production_order,
    release_material_reservation,
    reservation_plan_for_production_order,
    current_stock_for_item,
    reserved_stock_for_item,
    reserved_stock_for_batch,
    stock_summary_count,
    stock_summary_line_count,
    stock_summary,
)
from app.services.inventory_reports import (
    ReportLanguage,
    build_material_inventory_pdf,
    build_material_inventory_xlsx,
    material_inventory_report_rows,
    material_inventory_supplier_scope_label,
)
from app.core.pagination import clamp_pagination
from app.core.config import settings
from app.core.uploads import SAFE_IMAGE_EXTENSIONS, extension_for_upload, read_validated_upload_content

router = APIRouter(prefix="/inventory", tags=["inventory"])

EPSILON = 1e-9


def _locked_stock_batch_statement(batch_id: int):
    # StockBatch.item is joined eagerly by default. PostgreSQL rejects a broad
    # FOR UPDATE when that optional eager relationship adds an outer join, so
    # lock only the stock_batches query and load no relationship for deletion.
    return (
        select(StockBatch)
        .options(lazyload(StockBatch.item))
        .where(StockBatch.id == batch_id)
        .with_for_update()
    )


def _delete_stock_batch_receipt_movements(db: DbSession, movements: list[StockMovement]) -> None:
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


def _ensure_unique_active_item_name(db: DbSession, data: dict, item_id: int | None = None) -> None:
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


def _material_report_timestamp() -> tuple[str, str]:
    timestamp = datetime.now(ZoneInfo("Asia/Tashkent"))
    return timestamp.strftime("%Y-%m-%d %H:%M"), timestamp.strftime("%Y%m%d_%H%M")


def _resolve_supplier_scope(
    db: DbSession,
    supplier_id: int | None,
    supplier_unassigned: bool,
) -> Supplier | None:
    if supplier_id is not None and supplier_unassigned:
        raise HTTPException(400, "Choose either a supplier or unassigned stock, not both")
    if supplier_id is None:
        return None
    if supplier_id <= 0:
        raise HTTPException(400, "supplier_id must be a positive integer")
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier


@router.get("/reports/material-stock.xlsx")
def download_material_stock_excel(
    db: DbSession,
    lang: ReportLanguage = "uz",
    supplier_id: int | None = None,
    supplier_unassigned: bool = False,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    supplier = _resolve_supplier_scope(db, supplier_id, supplier_unassigned)
    generated_label, filename_timestamp = _material_report_timestamp()
    content = build_material_inventory_xlsx(
        material_inventory_report_rows(
            db,
            supplier_id=supplier_id,
            supplier_unassigned=supplier_unassigned,
        ),
        generated_label,
        lang,
        scope_label=material_inventory_supplier_scope_label(
            lang,
            supplier.name if supplier else None,
            supplier_unassigned,
        ),
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="material_inventory_report_{filename_timestamp}.xlsx"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/reports/material-stock.pdf")
def download_material_stock_pdf(
    db: DbSession,
    lang: ReportLanguage = "uz",
    supplier_id: int | None = None,
    supplier_unassigned: bool = False,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    supplier = _resolve_supplier_scope(db, supplier_id, supplier_unassigned)
    generated_label, filename_timestamp = _material_report_timestamp()
    content = build_material_inventory_pdf(
        material_inventory_report_rows(
            db,
            supplier_id=supplier_id,
            supplier_unassigned=supplier_unassigned,
        ),
        generated_label,
        lang,
        scope_label=material_inventory_supplier_scope_label(
            lang,
            supplier.name if supplier else None,
            supplier_unassigned,
        ),
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="material_inventory_report_{filename_timestamp}.pdf"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.get("/supplier-options")
def list_inventory_supplier_options(
    db: DbSession,
    group: str = "materials",
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
):
    categories = categories_for_group(group)
    if not categories:
        raise HTTPException(400, "Invalid inventory group")
    suppliers = (
        db.query(Supplier.id, Supplier.name)
        .join(StockBatch, StockBatch.supplier_id == Supplier.id)
        .join(Item, Item.id == StockBatch.item_id)
        .filter(
            Item.category.in_(categories),
            StockBatch.quantity > 0,
        )
        .group_by(Supplier.id, Supplier.name)
        .order_by(func.lower(Supplier.name), Supplier.name, Supplier.id)
        .all()
    )
    has_unassigned = bool(
        stock_summary(
            db,
            group=group,
            supplier_unassigned=True,
            positive_only=True,
        )
    )
    return {
        "rows": [{"id": int(supplier_id), "name": name} for supplier_id, name in suppliers],
        "has_unassigned": has_unassigned,
    }


# ===== Items =====
@router.get("/items")
def list_items(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
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


@router.post("/items/image/upload", status_code=201)
async def upload_item_image(
    file: UploadFile = File(...),
    _: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS)
    os.makedirs(settings.MODEL_FILES_DIR, exist_ok=True)
    safe_name = f"item_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.MODEL_FILES_DIR, safe_name)
    content = await read_validated_upload_content(file, ext, 10 * 1024 * 1024)
    with open(abs_path, "wb") as f:
        f.write(content)
    return {"file_url": f"/storage/model-files/{safe_name}"}


@router.patch("/items/{item_id}/image", response_model=ItemOut)
def update_item_image(
    item_id: int,
    payload: ItemImageIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    it = db.get(Item, item_id)
    if not it:
        raise HTTPException(404, "Item not found")
    old_value = {"image_url": it.image_url}
    it.image_url = _validate_item_image_url(payload.image_url)
    log_action(db, current, "update_image", "Item", it.id, old_value=old_value, new_value={"image_url": it.image_url})
    db.commit(); db.refresh(it)
    return it


@router.post("/items", response_model=ItemOut, status_code=201)
def create_item(payload: ItemIn, db: DbSession, current: User = Depends(require_permissions("storage.items", "*"))):
    if db.query(Item).filter(Item.sku == payload.sku).first():
        raise HTTPException(400, "SKU already exists")
    data = _item_payload(payload)
    _ensure_unique_active_item_name(db, data)
    it = Item(**data)
    db.add(it); db.flush()
    log_action(db, current, "create", "Item", it.id, new_value={"sku": it.sku})
    db.commit(); db.refresh(it)
    return it


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(
    item_id: int,
    payload: ItemIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "*")),
):
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


@router.delete("/items/{item_id}", status_code=204)
def delete_item(
    item_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "*")),
):
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
    if linked:
        raise HTTPException(409, "Item is linked to stock, BOM, purchasing, or waste records")
    db.delete(it)
    log_action(db, current, "delete", "Item", item_id, new_value={"sku": it.sku, "name": it.name})
    db.commit()


# ===== Warehouses =====
@router.get("/warehouses", response_model=list[WarehouseOut])
def list_warehouses(db: DbSession, _: User = Depends(require_permissions(*WAREHOUSE_READ_PERMISSIONS))):
    return db.query(Warehouse).order_by(Warehouse.id).all()


@router.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(payload: WarehouseIn, db: DbSession, current: User = Depends(require_permissions("admin.warehouses", "*"))):
    w = Warehouse(**payload.model_dump())
    db.add(w); db.flush()
    log_action(db, current, "create", "Warehouse", w.id)
    db.commit(); db.refresh(w)
    return w


# ===== Stock view =====
@router.get("/stock")
def get_stock(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    supplier_id: int | None = None,
    supplier_unassigned: bool = False,
    positive_only: bool = False,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    _resolve_supplier_scope(db, supplier_id, supplier_unassigned)
    safe_page, safe_size, _ = clamp_pagination(page, page_size)
    start, end = date_filter_bounds(created_from, created_to)
    total = (
        stock_summary_count(
            db,
            category,
            group,
            q,
            created_from=start,
            created_to=end,
            supplier_id=supplier_id,
            supplier_unassigned=supplier_unassigned,
            positive_only=positive_only,
        )
        if include_total
        else 0
    )
    line_total = (
        stock_summary_line_count(
            db,
            category,
            group,
            q,
            created_from=start,
            created_to=end,
            supplier_id=supplier_id,
            supplier_unassigned=supplier_unassigned,
        )
        if include_total
        else 0
    )
    rows = stock_summary(
        db,
        category,
        group,
        q,
        created_from=start,
        created_to=end,
        page=safe_page,
        page_size=safe_size,
        supplier_id=supplier_id,
        supplier_unassigned=supplier_unassigned,
        positive_only=positive_only,
    )
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
        return {
            "rows": out,
            "total": total,
            "item_total": total,
            "line_total": line_total,
            "page": safe_page,
            "page_size": safe_size,
        }
    return out


def _stock_adjustment_warehouse_id(db: DbSession, item: Item, batches: list[StockBatch]) -> int:
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


def _unique_adjustment_batch_no(db: DbSession, item: Item) -> str:
    base = f"{item.sku}-ADJ-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    candidate = base
    suffix = 1
    while db.query(StockBatch.id).filter(StockBatch.batch_no == candidate).first():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _apply_batch_tracked_stock_adjustment(
    db: DbSession,
    *,
    item: Item,
    delta: float,
    movement_type: str,
    user_id: int | None,
) -> list[StockMovement]:
    if abs(delta) <= EPSILON:
        return []
    batches = (
        db.query(StockBatch)
        .filter(StockBatch.item_id == item.id, StockBatch.unit == item.unit)
        .order_by(StockBatch.id.desc())
        .all()
    )
    movements: list[StockMovement] = []
    if delta > 0:
        batch = batches[0] if batches else None
        if not batch:
            batch = StockBatch(
                item_id=int(item.id),
                batch_no=_unique_adjustment_batch_no(db, item),
                quantity=0,
                unit=item.unit,
                cost_per_unit=float(item.default_cost or 0),
                warehouse_id=_stock_adjustment_warehouse_id(db, item, batches),
                qc_status="passed",
            )
            db.add(batch)
            db.flush()
        batch.quantity = float(batch.quantity or 0) + delta
        movement = StockMovement(
            movement_type=movement_type,
            item_id=int(item.id),
            batch_id=int(batch.id),
            to_warehouse_id=int(batch.warehouse_id),
            quantity=delta,
            unit=item.unit,
            reference_type="StockAdjustment",
            created_by=user_id,
        )
        db.add(movement)
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
        batch.quantity = available - qty
        movement = StockMovement(
            movement_type=movement_type,
            item_id=int(item.id),
            batch_id=int(batch.id),
            from_warehouse_id=int(batch.warehouse_id),
            quantity=qty,
            unit=item.unit,
            reference_type="StockAdjustment",
            created_by=user_id,
        )
        db.add(movement)
        movements.append(movement)
        left -= qty
    if left > EPSILON:
        raise HTTPException(409, f"Batch stock cannot be reduced by {abs(delta):g} {item.unit}; only {abs(delta) - left:g} is in batches")
    return movements


@router.patch("/stock/{item_id}", response_model=StockQuantityAdjustmentOut)
def set_stock_quantity(
    item_id: int,
    payload: StockQuantityAdjustmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "storage.transfer", "*")),
):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    unit = (payload.unit or item.unit or "").strip()
    if not unit:
        raise HTTPException(400, "Unit is required")
    if unit != item.unit:
        raise HTTPException(400, f"Stock unit must match item unit ({item.unit})")
    target_quantity = float(payload.quantity or 0)
    previous_quantity = current_stock_for_item(db, item_id)
    reserved_quantity = reserved_stock_for_item(db, item_id)
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

    movement_type = "adjustment" if delta > 0 else "issue"
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
        if active_batch_count > 1:
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
        movement = StockMovement(
            movement_type=movement_type,
            item_id=item_id,
            quantity=abs(delta),
            unit=item.unit,
            reference_type="StockAdjustment",
            created_by=current.id,
        )
        db.add(movement)
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


# ===== Receive (creates a batch + movement) =====
@router.post("/receive", response_model=StockBatchOut, status_code=201)
def receive_stock(
    payload: StockBatchIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.receive", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    if not db.get(Item, payload.item_id):
        raise HTTPException(404, "Item not found")
    if not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")
    batch_data = payload.model_dump()
    batch_data["image_url"] = _validate_item_image_url(batch_data.get("image_url"))
    batch = StockBatch(**batch_data)
    db.add(batch); db.flush()
    mv = StockMovement(
        movement_type="receive",
        item_id=payload.item_id,
        batch_id=batch.id,
        to_warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        unit=payload.unit,
        reference_type="StockBatch",
        reference_id=batch.id,
        created_by=current.id,
    )
    db.add(mv)
    log_action(db, current, "receive", "StockBatch", batch.id, new_value={"batch_no": batch.batch_no, "qty": float(batch.quantity)})
    db.flush()
    db.refresh(batch)
    response = StockBatchOut.model_validate(batch).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="inventory.receive",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    return response


@router.post("/accessory-returns", response_model=StockBatchOut, status_code=201)
def collect_back_accessory(
    payload: AccessoryReturnIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.receive", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.accessory-return", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

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
    if not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(404, "Warehouse not found")

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


# ===== Accessory issues to production =====
@router.get("/accessory-issue-plan", response_model=AccessoryIssuePlanOut)
def get_accessory_issue_plan(
    production_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
    return accessory_issue_plan(db, production_order_id)


@router.get("/accessory-issues")
def list_accessory_issues(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
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


@router.get("/accessory-issue-requests")
def list_accessory_issue_requests(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    production_order_id: int | None = None,
    model_id: int | None = None,
    q: str | None = None,
    include_complete: bool = False,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
):
    safe_page, safe_size, _ = clamp_pagination(page, page_size)
    all_rows = accessory_issue_requests(
        db,
        production_order_id=production_order_id,
        model_id=model_id,
        q=q,
        include_complete=include_complete,
    )
    rows = all_rows[(safe_page - 1) * safe_size: (safe_page - 1) * safe_size + safe_size]
    if include_total:
        return {
            "rows": [AccessoryIssueRequestRow(**row).model_dump() for row in rows],
            "total": len(all_rows),
            "page": safe_page,
            "page_size": safe_size,
        }
    return [AccessoryIssueRequestRow(**row).model_dump() for row in rows]


@router.post("/accessory-issues", response_model=AccessoryIssueOut, status_code=201)
def issue_accessories(
    payload: AccessoryIssueIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.transfer", "*")),
):
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


# ===== Material reservations =====
def _reservation_payload(reservation: MaterialReservation) -> dict:
    item = reservation.item
    batch = reservation.stock_batch
    warehouse = reservation.warehouse
    return {
        **MaterialReservationOut.model_validate(reservation).model_dump(),
        "item_sku": item.sku if item else None,
        "item_name": item.name if item else None,
        "batch_no": batch.batch_no if batch else None,
        "warehouse_name": warehouse.name if warehouse else None,
    }


def _reservation_status_payload(db: DbSession, production_order_id: int) -> dict:
    status = material_reservation_status_for_production_order(db, production_order_id)
    return {
        **status,
        "reservations": [_reservation_payload(row) for row in status["reservations"]],
    }


@router.get("/reservations", response_model=list[MaterialReservationOut])
def list_material_reservations(
    db: DbSession,
    _: User = Depends(require_permissions("inventory.reservations.view", "*")),
    production_order_id: int | None = None,
    sales_order_id: int | None = None,
    item_id: int | None = None,
    status: str | None = None,
):
    qry = db.query(MaterialReservation)
    if production_order_id is not None:
        qry = qry.filter(MaterialReservation.production_order_id == production_order_id)
    if sales_order_id is not None:
        qry = qry.filter(MaterialReservation.sales_order_id == sales_order_id)
    if item_id is not None:
        qry = qry.filter(MaterialReservation.item_id == item_id)
    if status:
        qry = qry.filter(MaterialReservation.status == status)
    rows = qry.order_by(MaterialReservation.created_at.desc(), MaterialReservation.id.desc()).all()
    return [_reservation_payload(row) for row in rows]


@router.get("/reservations/plan", response_model=MaterialReservationPlanOut)
def get_material_reservation_plan(
    production_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions("inventory.reservations.view", "planning.reserve_materials", "*")),
):
    return reservation_plan_for_production_order(db, production_order_id)


@router.post("/reservations", response_model=MaterialReservationOut, status_code=201)
def create_material_reservation(
    payload: MaterialReservationIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.create", "planning.reserve_materials", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.reservations.create", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay

    try:
        created = create_material_reservations(
            db,
            production_order_id=payload.production_order_id,
            lines=[payload.model_dump()],
            user_id=current.id,
            source="manual",
        )
    except HTTPException as exc:
        if exc.status_code in (400, 409):
            log_action(
                db,
                current,
                "failed_create_material_reservation",
                "MaterialReservation",
                None,
                new_value={"payload": payload.model_dump(), "detail": exc.detail},
            )
            db.commit()
        raise
    reservation = created[0]
    log_action(
        db,
        current,
        "create_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "reservation_no": reservation.reservation_no,
            "production_order_id": reservation.production_order_id,
            "item_id": reservation.item_id,
            "stock_batch_id": reservation.stock_batch_id,
            "reserved_quantity": float(reservation.reserved_quantity or 0),
        },
    )
    response = _reservation_payload(reservation)
    store_idempotent_response(
        db,
        scope="inventory.reservations.create",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit()
    db.refresh(reservation)
    return response


@router.post("/reservations/auto", status_code=201)
def auto_create_material_reservations(
    payload: MaterialReservationAutoIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.create", "planning.reserve_materials", "*")),
):
    result = auto_reserve_materials_for_production_order(
        db,
        production_order_id=payload.production_order_id,
        mode=payload.mode,
        reserve_accessories=payload.reserve_accessories,
        reserve_materials=payload.reserve_materials,
        reserve_packaging=payload.reserve_packaging,
        user_id=current.id,
    )
    reservations = result["reservations"]
    log_action(
        db,
        current,
        "auto_reserve_materials",
        "ProductionOrder",
        payload.production_order_id,
        new_value={
            "mode": payload.mode,
            "created_count": len(reservations),
            "reservation_ids": [int(row.id) for row in reservations],
        },
    )
    db.commit()
    return {
        "production_order_id": payload.production_order_id,
        "created_count": len(reservations),
        "reservations": [_reservation_payload(row) for row in reservations],
        "plan": result["plan"],
    }


@router.post("/reservations/{reservation_id}/release", response_model=MaterialReservationOut)
def release_reservation(
    reservation_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.release", "*")),
):
    reservation = release_material_reservation(db, reservation_id)
    log_action(
        db,
        current,
        "release_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "released_quantity": float(reservation.released_quantity or 0),
            "status": reservation.status,
        },
    )
    db.commit()
    db.refresh(reservation)
    return _reservation_payload(reservation)


@router.post("/reservations/{reservation_id}/consume", response_model=MaterialReservationOut)
def consume_reservation(
    reservation_id: int,
    payload: MaterialReservationConsumeIn,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.reservations.consume", "*")),
):
    reservation = consume_material_reservation(
        db,
        reservation_id,
        quantity=payload.quantity,
        user_id=current.id,
    )
    log_action(
        db,
        current,
        "consume_material_reservation",
        "MaterialReservation",
        reservation.id,
        new_value={
            "quantity": payload.quantity,
            "consumed_quantity": float(reservation.consumed_quantity or 0),
            "status": reservation.status,
        },
    )
    db.commit()
    db.refresh(reservation)
    return _reservation_payload(reservation)


# ===== Transfer =====
@router.post("/transfer", response_model=StockMovementOut, status_code=201)
def transfer_stock(
    payload: StockMovementIn,
    db: DbSession,
    current: User = Depends(require_permissions("storage.transfer", "*")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    fingerprint_payload = payload.model_dump(mode="json")
    replay = replay_idempotent_response(db, scope="inventory.transfer", key=idempotency_key, payload=fingerprint_payload)
    if replay:
        return replay
    if payload.movement_type not in ("transfer", "issue", "consume", "adjustment", "return"):
        raise HTTPException(400, "Invalid movement_type")
    mv = StockMovement(**payload.model_dump(), created_by=current.id)
    db.add(mv); db.flush()
    log_action(db, current, payload.movement_type, "StockMovement", mv.id)
    response = StockMovementOut.model_validate(mv).model_dump(mode="json")
    store_idempotent_response(
        db,
        scope="inventory.transfer",
        key=idempotency_key,
        payload=fingerprint_payload,
        response=response,
        user=current,
        status_code=201,
    )
    db.commit(); db.refresh(mv)
    return response


# ===== Batches =====
@router.patch("/batches/{batch_id}", response_model=StockBatchOut)
def update_batch(
    batch_id: int,
    payload: StockBatchUpdate,
    db: DbSession,
    current: User = Depends(require_permissions("storage.items", "storage.receive", "*")),
):
    batch = db.get(StockBatch, batch_id)
    if not batch:
        raise HTTPException(404, "Stock batch not found")
    item = db.get(Item, batch.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    values = payload.model_dump(exclude_unset=True)
    if not values:
        return batch

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
        values["qc_status"] = str(values["qc_status"] or "").strip().lower()
        if values["qc_status"] not in {"pending", "passed", "failed", "rejected", "hold"}:
            raise HTTPException(400, "Invalid QC status")
    if "image_url" in values:
        values["image_url"] = _validate_item_image_url(values["image_url"])

    target_quantity = float(values.get("quantity", old_quantity))
    if target_quantity + EPSILON < reserved_quantity:
        raise HTTPException(
            409,
            f"Quantity cannot be lower than reserved stock ({reserved_quantity:g} {old_unit})",
        )
    target_warehouse_id = int(values.get("warehouse_id", old_warehouse_id))
    target_unit = str(values.get("unit", old_unit))
    delta = target_quantity - old_quantity
    target_item = item
    item_movements: list[StockMovement] = []
    if "item_id" in values:
        if values["item_id"] is None:
            raise HTTPException(400, "Material is required")
        target_item = db.get(Item, int(values["item_id"]))
        if not target_item:
            raise HTTPException(404, "Material not found")
        if not target_item.is_active:
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
                or db.query(CuttingRecord.id).filter(CuttingRecord.fabric_batch_id == batch_id).first()
                or db.query(WasteRecord.id).filter(WasteRecord.batch_id == batch_id).first()
            )
            item_movements = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).all()
            has_downstream_movement = any(
                movement.movement_type != "receive"
                or movement.reference_type != "StockBatch"
                or int(movement.reference_id or 0) != batch_id
                for movement in item_movements
            )
            if reserved_quantity > EPSILON or linked or has_downstream_movement:
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

    for key, value in values.items():
        setattr(batch, key, value)
    if target_item.id != item.id:
        for movement in item_movements:
            movement.item_id = target_item.id
        item = target_item

    if abs(delta) > EPSILON:
        db.add(StockMovement(
            movement_type="adjustment" if delta > 0 else "issue",
            item_id=batch.item_id,
            batch_id=batch.id,
            from_warehouse_id=old_warehouse_id if delta < 0 else None,
            to_warehouse_id=old_warehouse_id if delta > 0 else None,
            quantity=abs(delta),
            unit=target_unit,
            reference_type="StockBatchAdjustment",
            reference_id=batch.id,
            created_by=current.id,
        ))
    if target_warehouse_id != old_warehouse_id and target_quantity > EPSILON:
        db.add(StockMovement(
            movement_type="transfer",
            item_id=batch.item_id,
            batch_id=batch.id,
            from_warehouse_id=old_warehouse_id,
            to_warehouse_id=target_warehouse_id,
            quantity=target_quantity,
            unit=target_unit,
            reference_type="StockBatchEdit",
            reference_id=batch.id,
            created_by=current.id,
        ))

    db.flush()
    new_value = {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in values.items()
    }
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


@router.delete("/batches/{batch_id}", status_code=204)
def delete_unused_batch(
    batch_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("inventory.batches.delete", "*")),
):
    batch = db.execute(_locked_stock_batch_statement(batch_id)).scalar_one_or_none()
    if not batch:
        raise HTTPException(404, "Stock batch not found")

    linked = (
        db.query(MaterialReservation.id).filter(MaterialReservation.stock_batch_id == batch_id).first()
        or db.query(ModelBOM.id).filter(ModelBOM.stock_batch_id == batch_id).first()
        or db.query(ProductionOrder.id).filter(ProductionOrder.fabric_batch_id == batch_id).first()
        or db.query(CuttingRecord.id).filter(CuttingRecord.fabric_batch_id == batch_id).first()
        or db.query(WasteRecord.id).filter(WasteRecord.batch_id == batch_id).first()
    )
    movements = db.query(StockMovement).filter(StockMovement.batch_id == batch_id).all()
    has_downstream_movement = any(
        movement.movement_type != "receive"
        or movement.reference_type != "StockBatch"
        or int(movement.reference_id or 0) != batch_id
        for movement in movements
    )
    if linked or has_downstream_movement:
        raise HTTPException(409, "Stock batch is already reserved or used and cannot be deleted")

    old_value = {
        "batch_no": batch.batch_no,
        "item_id": batch.item_id,
        "quantity": float(batch.quantity or 0),
        "unit": batch.unit,
        "warehouse_id": batch.warehouse_id,
        "supplier_id": batch.supplier_id,
    }
    _delete_stock_batch_receipt_movements(db, movements)
    db.delete(batch)
    log_action(db, current, "delete", "StockBatch", batch_id, old_value=old_value)
    db.commit()


@router.get("/batches")
def list_batches(
    db: DbSession,
    _: User = Depends(require_permissions(*INVENTORY_READ_PERMISSIONS)),
    item_id: int | None = None,
    item_ids: str | None = None,
    category: str | None = None,
    group: str | None = None,
    q: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    supplier_id: int | None = None,
    supplier_unassigned: bool = False,
    page: int = 1,
    page_size: int = 500,
    include_total: bool = False,
    hide_empty: bool = False,
):
    _resolve_supplier_scope(db, supplier_id, supplier_unassigned)
    qry = (
        db.query(StockBatch, Item, Warehouse, Supplier)
        .join(Item, Item.id == StockBatch.item_id)
        .join(Warehouse, Warehouse.id == StockBatch.warehouse_id)
        .outerjoin(Supplier, Supplier.id == StockBatch.supplier_id)
    )
    if supplier_id is not None:
        qry = qry.filter(StockBatch.supplier_id == supplier_id)
    elif supplier_unassigned:
        qry = qry.filter(StockBatch.supplier_id.is_(None))
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
                StockBatch.color.ilike(like),
                StockBatch.old_code.ilike(like),
                StockBatch.color_code.ilike(like),
                StockBatch.color_status.ilike(like),
                StockBatch.order_no.ilike(like),
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
    total = qry.count() if include_total else 0
    qry = qry.order_by(StockBatch.received_date.desc(), StockBatch.id.desc())
    qry = qry.offset(offset).limit(safe_size)
    rows = qry.all()
    batch_ids = [int(batch.id) for batch, _, _, _ in rows]
    active_reservations: dict[int, list[dict]] = {batch_id: [] for batch_id in batch_ids}
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
            remaining = max(
                0.0,
                float(reservation.reserved_quantity or 0)
                - float(reservation.consumed_quantity or 0)
                - float(reservation.released_quantity or 0),
            )
            active_reservations.setdefault(int(reservation.stock_batch_id), []).append({
                "id": int(reservation.id),
                "reservation_no": reservation.reservation_no,
                "production_order_id": int(reservation.production_order_id),
                "reserved_quantity": float(reservation.reserved_quantity or 0),
                "remaining_quantity": remaining,
                "unit": reservation.unit,
                "status": reservation.status,
            })
    out = []
    for batch, item, warehouse, supplier in rows:
        reserved_qty = reserved_stock_for_batch(db, int(batch.id))
        out.append({
            **StockBatchOut.model_validate(batch).model_dump(),
            "item_sku": item.sku if item else None,
            "item_name": item.name if item else None,
            "item_category": item.category if item else None,
            "supplier_name": supplier.name if supplier else None,
            "warehouse_name": warehouse.name if warehouse else None,
            "reserved_quantity": reserved_qty,
            "available_quantity": available_stock_for_batch(db, int(batch.id)),
            "active_reservations": active_reservations.get(int(batch.id), []),
        })
    if include_total:
        return {"rows": out, "total": total, "page": safe_page, "page_size": safe_size}
    return out
