"""Package service: build packages of finished goods with QR/barcode."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Package, PackageItem, PackageBatchAllocation, PackageScanLog, PackageChangeRequest,
    ProductionOrder, FinishedGoodsStock, Warehouse, ModelBOM, StockBatch,
    ProductionBatch, StockReservation, ShipmentPackage, User, Notification,
    PackagingRecord, WorkOrder,
)
from app.core.deps import user_permissions
from app.services.barcode import generate_barcode_value, save_qr_image, save_barcode_image
from app.services.finished_goods import infer_brand_and_collection
from app.services.numbering import next_package_no
from app.services.workflow import (
    decrement_finished_goods_for_package,
    notify_department,
    sync_production_order_status,
    sync_storage_transfer_work_order,
)


WAREHOUSE_MAP_LAYOUT: tuple[tuple[str, int], ...] = (
    ("N", 16),
    ("A", 12),
    ("B", 12),
    ("C", 16),
    ("D", 20),
    ("E", 20),
    ("F", 20),
    ("G", 16),
    ("H", 20),
    ("M", 12),
    ("K", 2),
    ("L", 5),
)
VALID_STORAGE_CELLS = {
    f"{zone}-{idx:02d}"
    for zone, size in WAREHOUSE_MAP_LAYOUT
    for idx in range(1, size + 1)
}
VALID_STORAGE_SHELVES = {"S1", "S2"}
PACKAGE_CHANGE_ALLOWED_STATUSES = {"packed", "received_in_storage"}
PACKAGE_CHANGE_PENDING_STATUS = "pending"


def _sync_package_production(db: Session, production_order_id: int | None) -> None:
    """Sync production workflow only for production-backed packages."""
    if production_order_id is None:
        return
    sync_storage_transfer_work_order(db, production_order_id)
    sync_production_order_status(db, production_order_id)


def normalize_storage_cell(cell: str | None) -> str | None:
    if cell is None:
        return None
    normalized = cell.strip().upper()
    if not normalized:
        return None
    return normalized


def normalize_storage_shelf(shelf: str | None) -> str | None:
    if shelf is None:
        return None
    normalized = shelf.strip().upper()
    if not normalized:
        return None
    return normalized


def validate_storage_location(
    storage_cell: str | None,
    storage_shelf: str | None,
    *,
    require_cell: bool,
) -> tuple[str | None, str | None]:
    cell = normalize_storage_cell(storage_cell)
    shelf = normalize_storage_shelf(storage_shelf)

    if require_cell and not cell:
        raise HTTPException(400, "storage_cell is required")
    if not cell and shelf:
        raise HTTPException(400, "storage_shelf requires storage_cell")

    if cell and cell not in VALID_STORAGE_CELLS:
        raise HTTPException(400, f"Unknown storage cell '{cell}'")

    if cell and not shelf:
        shelf = "S1"

    if shelf and shelf not in VALID_STORAGE_SHELVES:
        raise HTTPException(400, "storage_shelf must be S1 or S2")

    return cell, shelf


def format_storage_location(storage_cell: str | None, storage_shelf: str | None) -> str | None:
    if not storage_cell:
        return None
    if storage_shelf:
        return f"{storage_cell}/{storage_shelf}"
    return storage_cell


def package_snapshot(pkg: Package) -> dict:
    return {
        "id": pkg.id,
        "package_no": pkg.package_no,
        "barcode": pkg.barcode,
        "production_order_id": pkg.production_order_id,
        "production_batch_id": pkg.production_batch_id,
        "sales_order_id": pkg.sales_order_id,
        "brand_id": pkg.brand_id,
        "collection_id": pkg.collection_id,
        "model_id": pkg.model_id,
        "color": pkg.color,
        "package_type": pkg.package_type,
        "total_quantity": int(pkg.total_quantity or 0),
        "capacity": int(pkg.capacity or 0),
        "weight_kg": float(pkg.weight_kg) if pkg.weight_kg is not None else None,
        "warehouse_id": pkg.warehouse_id,
        "storage_cell": pkg.storage_cell,
        "storage_shelf": pkg.storage_shelf,
        "status": pkg.status,
        "notes": pkg.notes,
        "items": [
            {
                "model_id": int(it.model_id),
                "color": it.color,
                "size": it.size,
                "quantity": int(it.quantity or 0),
            }
            for it in sorted((pkg.items or []), key=lambda row: row.id)
        ],
        "batch_allocations": [
            {
                "production_batch_id": int(alloc.production_batch_id),
                "quantity": int(alloc.quantity or 0),
            }
            for alloc in sorted((pkg.batch_allocations or []), key=lambda row: row.id)
        ],
    }


def _compute_cost(db: Session, model_id: int) -> float:
    """Estimate cost-per-piece from BOM × avg batch cost. Used for finished goods valuation."""
    cost = 0.0
    bom = db.query(ModelBOM).filter(ModelBOM.model_id == model_id).all()
    for b in bom:
        avg_cost_row = db.query(StockBatch).filter(StockBatch.item_id == b.item_id).order_by(StockBatch.id.desc()).first()
        unit_cost = float(avg_cost_row.cost_per_unit) if avg_cost_row else 0.0
        cost += float(b.quantity_per_piece) * unit_cost * (1.0 + float(b.waste_percent) / 100.0)
    return round(cost, 4)


def _packaging_record_totals_by_batch(db: Session, production_order_id: int) -> dict[int | None, int]:
    rows = (
        db.query(PackagingRecord.production_batch_id, func.coalesce(func.sum(PackagingRecord.packed_qty), 0))
        .join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .group_by(PackagingRecord.production_batch_id)
        .all()
    )
    return {int(batch_id) if batch_id is not None else None: int(qty or 0) for batch_id, qty in rows}


def _existing_package_totals_by_batch(
    db: Session,
    production_order_id: int,
    *,
    exclude_package_id: int | None = None,
) -> dict[int | None, int]:
    totals: dict[int | None, int] = {}
    allocated_ids: set[int] = set()

    allocation_qry = (
        db.query(
            PackageBatchAllocation.package_id,
            PackageBatchAllocation.production_batch_id,
            func.coalesce(func.sum(PackageBatchAllocation.quantity), 0),
        )
        .join(Package, Package.id == PackageBatchAllocation.package_id)
        .filter(Package.production_order_id == production_order_id)
    )
    if exclude_package_id:
        allocation_qry = allocation_qry.filter(Package.id != exclude_package_id)
    for package_id, batch_id, qty in allocation_qry.group_by(
        PackageBatchAllocation.package_id,
        PackageBatchAllocation.production_batch_id,
    ).all():
        allocated_ids.add(int(package_id))
        key = int(batch_id) if batch_id is not None else None
        totals[key] = totals.get(key, 0) + int(qty or 0)

    fallback_qry = (
        db.query(Package.production_batch_id, func.coalesce(func.sum(Package.total_quantity), 0))
        .filter(Package.production_order_id == production_order_id)
    )
    if exclude_package_id:
        fallback_qry = fallback_qry.filter(Package.id != exclude_package_id)
    if allocated_ids:
        fallback_qry = fallback_qry.filter(~Package.id.in_(allocated_ids))
    for batch_id, qty in fallback_qry.group_by(Package.production_batch_id).all():
        key = int(batch_id) if batch_id is not None else None
        totals[key] = totals.get(key, 0) + int(qty or 0)
    return totals


def _enforce_packaged_quantity_available(
    db: Session,
    *,
    production_order_id: int,
    allocations: list[dict[str, int]],
    total: int,
    exclude_package_id: int | None = None,
) -> None:
    packed_by_batch = _packaging_record_totals_by_batch(db, production_order_id)
    if not packed_by_batch:
        return

    existing_by_batch = _existing_package_totals_by_batch(
        db,
        production_order_id,
        exclude_package_id=exclude_package_id,
    )
    requested_by_batch: dict[int | None, int] = {}
    if allocations:
        for alloc in allocations:
            batch_id = int(alloc["production_batch_id"])
            requested_by_batch[batch_id] = requested_by_batch.get(batch_id, 0) + int(alloc["quantity"])
    else:
        requested_by_batch[None] = int(total)

    for batch_id, requested in requested_by_batch.items():
        packed = int(packed_by_batch.get(batch_id, 0))
        existing = int(existing_by_batch.get(batch_id, 0))
        available = max(0, packed - existing)
        if requested > available:
            label = f"batch #{batch_id}" if batch_id is not None else "this production order"
            raise HTTPException(
                400,
                f"Package quantity {requested} exceeds available packed quantity {available} for {label}",
            )


def create_package(
    db: Session,
    *,
    production_order_id: int,
    production_batch_id: int | None = None,
    model_id: int,
    color: str,
    items: list[dict],
    sales_order_id: int | None = None,
    brand_id: int | None = None,
    collection_id: int | None = None,
    package_type: str = "bag",
    capacity: int = 60,
    weight_kg: float | None = None,
    batch_allocations: list[dict] | None = None,
    warehouse_id: int | None = None,
    override_capacity: bool = False,
    is_admin: bool = False,
    user_id: int | None = None,
    notes: str | None = None,
) -> Package:
    if not items:
        raise HTTPException(400, "Package must contain at least one size line")

    total = 0
    for item in items:
        try:
            item_model_id = int(item.get("model_id", model_id))
            quantity = int(item.get("quantity", 0))
        except (TypeError, ValueError):
            raise HTTPException(400, "Package item model and quantity must be numbers")
        if item_model_id <= 0:
            raise HTTPException(400, "Package item model is required")
        if not str(item.get("color") or "").strip():
            raise HTTPException(400, "Package item color is required")
        if not str(item.get("size") or "").strip():
            raise HTTPException(400, "Package item size is required")
        if quantity <= 0:
            raise HTTPException(400, "Package item quantity must be > 0")
        total += quantity
    if total <= 0:
        raise HTTPException(400, "Total package quantity must be > 0")
    if total > capacity and not (override_capacity and is_admin):
        raise HTTPException(400, f"Package quantity {total} exceeds capacity {capacity}. Admin override required.")
    normalized_weight_kg = None
    if weight_kg is not None:
        normalized_weight_kg = round(float(weight_kg), 4)
        if normalized_weight_kg < 0:
            raise HTTPException(400, "Package weight must be >= 0")

    # All items must share the same model unless admin override
    distinct_models = {int(it.get("model_id", model_id)) for it in items}
    if len(distinct_models) > 1 and not (override_capacity and is_admin):
        raise HTTPException(400, "Package contains different models — admin override required")
    # All items must share the same color (rule)
    distinct_colors = {it["color"] for it in items}
    if len(distinct_colors) > 1 and not (override_capacity and is_admin):
        raise HTTPException(400, "Package contains different colors — admin override required")

    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    batch_id = int(production_batch_id) if production_batch_id else None
    has_batches = db.query(ProductionBatch.id).filter(ProductionBatch.production_order_id == po.id).first()
    normalized_allocations: list[dict[str, int]] = []
    if batch_allocations:
        if not has_batches:
            raise HTTPException(400, "Batch allocations require a batched production order")
        batch_totals: dict[int, int] = {}
        for raw in batch_allocations:
            try:
                alloc_batch_id = int(raw.get("production_batch_id") or 0)
                qty = int(raw.get("quantity") or 0)
            except (TypeError, ValueError):
                raise HTTPException(400, "Invalid batch allocation")
            if alloc_batch_id <= 0 or qty <= 0:
                raise HTTPException(400, "Batch allocation quantities must be > 0")
            batch_exists = db.query(ProductionBatch.id).filter(
                ProductionBatch.id == alloc_batch_id,
                ProductionBatch.production_order_id == po.id,
            ).first()
            if not batch_exists:
                raise HTTPException(404, "Production batch not found for this production order")
            batch_totals[alloc_batch_id] = batch_totals.get(alloc_batch_id, 0) + qty
        if sum(batch_totals.values()) != total:
            raise HTTPException(400, "Batch allocation quantity must equal package total quantity")
        normalized_allocations = [
            {"production_batch_id": bid, "quantity": qty}
            for bid, qty in sorted(batch_totals.items())
        ]
        batch_id = normalized_allocations[0]["production_batch_id"] if len(normalized_allocations) == 1 else None
    elif batch_id is not None:
        batch_exists = db.query(ProductionBatch.id).filter(
            ProductionBatch.id == batch_id,
            ProductionBatch.production_order_id == po.id,
        ).first()
        if not batch_exists:
            raise HTTPException(404, "Production batch not found for this production order")
        normalized_allocations = [{"production_batch_id": batch_id, "quantity": total}]
    elif has_batches:
        raise HTTPException(400, "Select a production batch for this package")

    _enforce_packaged_quantity_available(
        db,
        production_order_id=production_order_id,
        allocations=normalized_allocations,
        total=total,
    )

    resolved_sales_order_id = sales_order_id if sales_order_id is not None else po.sales_order_id
    resolved_brand_id, resolved_collection_id = infer_brand_and_collection(
        db,
        model_id=model_id,
        sales_order_id=resolved_sales_order_id,
        production_order_id=production_order_id,
        package_id=None,
        brand_id=brand_id,
        collection_id=collection_id if collection_id is not None else po.collection_id,
    )

    pkg_no = next_package_no(db)
    barcode_value = generate_barcode_value("PKG")
    pkg = Package(
        package_no=pkg_no,
        barcode=barcode_value,
        production_order_id=production_order_id,
        production_batch_id=batch_id,
        sales_order_id=resolved_sales_order_id,
        brand_id=resolved_brand_id,
        collection_id=resolved_collection_id,
        model_id=model_id,
        color=color,
        package_type=package_type,
        total_quantity=total,
        capacity=capacity,
        weight_kg=normalized_weight_kg,
        warehouse_id=warehouse_id,
        status="packed",
        packed_by=user_id,
        packed_at=datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(pkg)
    db.flush()

    for it in items:
        db.add(PackageItem(
            package_id=pkg.id,
            model_id=int(it.get("model_id", model_id)),
            color=it["color"],
            size=it["size"],
            quantity=int(it["quantity"]),
        ))

    for alloc in normalized_allocations:
        db.add(PackageBatchAllocation(
            package_id=pkg.id,
            production_batch_id=alloc["production_batch_id"],
            quantity=alloc["quantity"],
        ))

    qr_payload = f"PACKAGE:{pkg_no}|{barcode_value}"
    pkg.qr_code_url = save_qr_image(qr_payload, f"package_qr_{pkg_no}")
    save_barcode_image(barcode_value, f"package_bc_{pkg_no}")

    db.add(PackageScanLog(
        package_id=pkg.id, scanned_by=user_id, scan_type="packed",
    ))

    # Add to finished goods stock (per size line)
    cost = _compute_cost(db, model_id)
    for it in items:
        db.add(FinishedGoodsStock(
            production_order_id=production_order_id,
            sales_order_id=resolved_sales_order_id,
            package_id=pkg.id,
            model_id=int(it.get("model_id", model_id)),
            brand_id=resolved_brand_id,
            collection_id=resolved_collection_id,
            color=it["color"],
            size=it["size"],
            quantity=int(it["quantity"]),
            available_qty=int(it["quantity"]),
            cost_per_piece=cost,
            warehouse_id=warehouse_id,
            status="available",
        ))

    db.flush()
    # Storage transfer stage becomes actionable as soon as a package exists.
    sync_production_order_status(db, production_order_id)
    notify_department(
        db,
        department_code="FGS",
        title="New package packed",
        message=f"Package {pkg.package_no} is ready for storage receive.",
        link="/packages/scan",
        exclude_user_id=user_id,
    )
    return pkg


def create_packages_bulk(
    db: Session,
    *,
    count: int,
    production_order_id: int,
    production_batch_id: int | None = None,
    model_id: int,
    color: str,
    items: list[dict],
    sales_order_id: int | None = None,
    brand_id: int | None = None,
    collection_id: int | None = None,
    package_type: str = "bag",
    capacity: int = 60,
    weight_kg: float | None = None,
    weight_kg_values: list[float | None] | None = None,
    batch_allocations: list[dict] | None = None,
    warehouse_id: int | None = None,
    override_capacity: bool = False,
    is_admin: bool = False,
    user_id: int | None = None,
    notes: str | None = None,
) -> list[Package]:
    if count <= 0:
        raise HTTPException(400, "count must be > 0")
    if count > 500:
        raise HTTPException(400, "count is too large (max 500)")
    normalized_weights: list[float | None] = []
    if weight_kg_values:
        if len(weight_kg_values) != count:
            raise HTTPException(400, "weight_kg_values length must match count")
        for raw in weight_kg_values:
            if raw is None:
                normalized_weights.append(None)
                continue
            try:
                value = round(float(raw), 4)
            except (TypeError, ValueError):
                raise HTTPException(400, "weight_kg_values must contain numbers or null")
            if value < 0:
                raise HTTPException(400, "Package weight must be >= 0")
            normalized_weights.append(value)
    created: list[Package] = []
    for index in range(count):
        package_weight = normalized_weights[index] if normalized_weights else weight_kg
        created.append(
            create_package(
                db,
                production_order_id=production_order_id,
                production_batch_id=production_batch_id,
                model_id=model_id,
                color=color,
                items=items,
                sales_order_id=sales_order_id,
                brand_id=brand_id,
                collection_id=collection_id,
                package_type=package_type,
                capacity=capacity,
                weight_kg=package_weight,
                batch_allocations=batch_allocations,
                warehouse_id=warehouse_id,
                override_capacity=override_capacity,
                is_admin=is_admin,
                user_id=user_id,
                notes=notes,
            )
        )
    return created


def _package_has_production_batches(db: Session, production_order_id: int) -> bool:
    return bool(
        db.query(ProductionBatch.id)
        .filter(ProductionBatch.production_order_id == production_order_id)
        .first()
    )


def _normalize_optional_int(value, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field_name} must be a number")
    return parsed


def _normalize_optional_weight(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = round(float(value), 4)
    except (TypeError, ValueError):
        raise HTTPException(400, "weight_kg must be a number")
    if parsed < 0:
        raise HTTPException(400, "Package weight must be >= 0")
    return parsed


def _normalize_package_items(pkg: Package, payload: dict, target_color: str) -> list[dict]:
    if "items" not in payload:
        return [
            {
                "model_id": int(it.model_id),
                "color": it.color,
                "size": it.size,
                "quantity": int(it.quantity or 0),
            }
            for it in sorted((pkg.items or []), key=lambda row: row.id)
        ]

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(400, "Package must contain at least one size line")

    merged: dict[tuple[int, str, str], int] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HTTPException(400, "Invalid package item")
        model_id = _normalize_optional_int(raw.get("model_id"), "model_id") or int(pkg.model_id)
        if model_id != int(pkg.model_id):
            raise HTTPException(400, "Package model cannot be changed. Delete and recreate the package instead.")
        color = str(raw.get("color") or target_color or "").strip()
        size = str(raw.get("size") or "").strip()
        try:
            qty = int(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Package item quantity must be a number")
        if not color:
            raise HTTPException(400, "Package item color is required")
        if not size:
            raise HTTPException(400, "Package item size is required")
        if qty <= 0:
            raise HTTPException(400, "Package item quantity must be > 0")
        key = (model_id, color, size)
        merged[key] = merged.get(key, 0) + qty

    return [
        {"model_id": model_id, "color": color, "size": size, "quantity": quantity}
        for (model_id, color, size), quantity in sorted(merged.items(), key=lambda item: (item[0][2], item[0][1], item[0][0]))
    ]


def _validate_batch_allocations(
    db: Session,
    pkg: Package,
    raw_allocations: list,
    total: int,
) -> list[dict]:
    if not raw_allocations:
        raise HTTPException(400, "Batch allocation is required for this production order")

    batch_totals: dict[int, int] = {}
    for raw in raw_allocations:
        if not isinstance(raw, dict):
            raise HTTPException(400, "Invalid batch allocation")
        batch_id = _normalize_optional_int(raw.get("production_batch_id"), "production_batch_id")
        try:
            qty = int(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Batch allocation quantity must be a number")
        if not batch_id or qty <= 0:
            raise HTTPException(400, "Batch allocation quantities must be > 0")
        batch_exists = db.query(ProductionBatch.id).filter(
            ProductionBatch.id == batch_id,
            ProductionBatch.production_order_id == pkg.production_order_id,
        ).first()
        if not batch_exists:
            raise HTTPException(404, "Production batch not found for this production order")
        batch_totals[batch_id] = batch_totals.get(batch_id, 0) + qty

    if sum(batch_totals.values()) != total:
        raise HTTPException(400, "Batch allocation quantity must equal package total quantity")

    return [
        {"production_batch_id": batch_id, "quantity": quantity}
        for batch_id, quantity in sorted(batch_totals.items())
    ]


def _normalize_package_batch_allocations(
    db: Session,
    pkg: Package,
    payload: dict,
    total: int,
) -> list[dict]:
    if pkg.production_order_id is None:
        raw_allocations = payload.get("batch_allocations") or []
        if raw_allocations:
            raise HTTPException(400, "Legacy stock packages cannot use production batch allocations")
        return []
    has_batches = _package_has_production_batches(db, pkg.production_order_id)
    if "batch_allocations" in payload:
        raw_allocations = payload.get("batch_allocations") or []
        if not has_batches:
            if raw_allocations:
                raise HTTPException(400, "This production order does not use batch allocations")
            return []
        return _validate_batch_allocations(db, pkg, raw_allocations, total)

    if not has_batches:
        return []

    current = [
        {"production_batch_id": int(alloc.production_batch_id), "quantity": int(alloc.quantity or 0)}
        for alloc in sorted((pkg.batch_allocations or []), key=lambda row: row.id)
    ]
    if len(current) == 1:
        return [{"production_batch_id": current[0]["production_batch_id"], "quantity": total}]
    if len(current) > 1:
        if sum(int(row["quantity"] or 0) for row in current) != total:
            raise HTTPException(400, "Update batch allocation quantities when changing package total quantity")
        return current
    if pkg.production_batch_id:
        return [{"production_batch_id": int(pkg.production_batch_id), "quantity": total}]
    raise HTTPException(400, "Batch allocation is required for this production order")


def normalize_package_edit_payload(db: Session, pkg: Package, payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(400, "Edit request payload is required")

    package_type = str(payload.get("package_type", pkg.package_type) or "bag").strip()
    if not package_type:
        raise HTTPException(400, "package_type is required")
    if len(package_type) > 16:
        raise HTTPException(400, "package_type is too long")

    try:
        capacity = int(payload.get("capacity", pkg.capacity or 60))
    except (TypeError, ValueError):
        raise HTTPException(400, "capacity must be a number")
    if capacity <= 0:
        raise HTTPException(400, "capacity must be > 0")

    color = str(payload.get("color", pkg.color) or "").strip()
    if not color:
        raise HTTPException(400, "color is required")

    weight_kg = _normalize_optional_weight(payload.get("weight_kg", pkg.weight_kg))
    warehouse_id = _normalize_optional_int(payload.get("warehouse_id", pkg.warehouse_id), "warehouse_id")
    if warehouse_id is not None and not db.get(Warehouse, warehouse_id):
        raise HTTPException(404, "Warehouse not found")

    storage_cell = payload.get("storage_cell", pkg.storage_cell)
    storage_shelf = payload.get("storage_shelf", pkg.storage_shelf)
    cell, shelf = validate_storage_location(storage_cell, storage_shelf, require_cell=False)

    items = _normalize_package_items(pkg, payload, color)
    total = sum(int(row["quantity"] or 0) for row in items)
    if total <= 0:
        raise HTTPException(400, "Total package quantity must be > 0")
    if total > capacity:
        raise HTTPException(400, f"Package quantity {total} exceeds capacity {capacity}")

    batch_allocations = _normalize_package_batch_allocations(db, pkg, payload, total)
    production_batch_id = batch_allocations[0]["production_batch_id"] if len(batch_allocations) == 1 else None
    if pkg.production_order_id is not None:
        _enforce_packaged_quantity_available(
            db,
            production_order_id=int(pkg.production_order_id),
            allocations=batch_allocations,
            total=total,
            exclude_package_id=int(pkg.id),
        )

    notes = payload.get("notes", pkg.notes)
    return {
        "color": color,
        "package_type": package_type,
        "capacity": capacity,
        "weight_kg": weight_kg,
        "warehouse_id": warehouse_id,
        "storage_cell": cell,
        "storage_shelf": shelf,
        "notes": notes,
        "items": items,
        "batch_allocations": batch_allocations,
        "production_batch_id": production_batch_id,
        "total_quantity": total,
    }


def _ensure_package_can_change(db: Session, pkg: Package) -> list[FinishedGoodsStock]:
    if pkg.status not in PACKAGE_CHANGE_ALLOWED_STATUSES:
        raise HTTPException(400, f"Package in status '{pkg.status}' cannot be edited or deleted")
    if db.query(StockReservation.id).filter(StockReservation.package_id == pkg.id).first():
        raise HTTPException(409, "Package has stock reservations and cannot be edited or deleted")
    if db.query(ShipmentPackage.id).filter(ShipmentPackage.package_id == pkg.id).first():
        raise HTTPException(409, "Package is attached to a shipment and cannot be edited or deleted")

    rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg.id).all()
    for row in rows:
        if int(row.reserved_qty or 0) > 0 or int(row.sold_qty or 0) > 0:
            raise HTTPException(409, "Package stock is already reserved or sold")
    return rows


def _is_package_change_approver(user: User) -> bool:
    role_name = (user.role.name if user.role else "").lower()
    perms = set(user_permissions(user))
    return "*" in perms or "management.approve" in perms or role_name in {"admin", "management"}


def _notify_package_change_approvers(
    db: Session,
    *,
    request: PackageChangeRequest,
    package_no: str,
    request_type: str,
    exclude_user_id: int | None,
) -> int:
    created = 0
    users = db.query(User).filter(User.is_active.is_(True)).all()
    for user in users:
        if exclude_user_id and user.id == exclude_user_id:
            continue
        if not _is_package_change_approver(user):
            continue
        db.add(
            Notification(
                user_id=user.id,
                title=f"Package {request_type} approval needed",
                message=f"{package_no} has a pending {request_type} request.",
                link="/packages",
            )
        )
        created += 1
    return created


def _notify_package_requester(
    db: Session,
    *,
    request: PackageChangeRequest,
    title: str,
    message: str,
) -> None:
    if not request.requested_by:
        return
    db.add(
        Notification(
            user_id=request.requested_by,
            title=title,
            message=message,
            link="/packages",
        )
    )


def create_package_change_request(
    db: Session,
    *,
    pkg: Package,
    request_type: str,
    payload: dict | None,
    reason: str | None,
    user_id: int | None,
) -> PackageChangeRequest:
    if request_type not in {"edit", "delete"}:
        raise HTTPException(400, "request_type must be edit or delete")
    _ensure_package_can_change(db, pkg)

    existing = db.query(PackageChangeRequest).filter(
        PackageChangeRequest.package_id == pkg.id,
        PackageChangeRequest.status == PACKAGE_CHANGE_PENDING_STATUS,
    ).first()
    if existing:
        raise HTTPException(409, "Package already has a pending edit/delete request")

    target_payload = normalize_package_edit_payload(db, pkg, payload) if request_type == "edit" else None
    request = PackageChangeRequest(
        package_id=pkg.id,
        package_no=pkg.package_no,
        request_type=request_type,
        status=PACKAGE_CHANGE_PENDING_STATUS,
        before_json=package_snapshot(pkg),
        payload_json=target_payload,
        reason=reason,
        requested_by=user_id,
    )
    db.add(request)
    db.flush()
    _notify_package_change_approvers(
        db,
        request=request,
        package_no=pkg.package_no,
        request_type=request_type,
        exclude_user_id=user_id,
    )
    return request


def _replace_finished_goods_for_package(
    db: Session,
    pkg: Package,
    items: list[dict],
) -> None:
    for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg.id).all():
        db.delete(row)
    db.flush()

    cost = _compute_cost(db, pkg.model_id)
    for item in items:
        qty = int(item["quantity"])
        db.add(
            FinishedGoodsStock(
                production_order_id=pkg.production_order_id,
                sales_order_id=pkg.sales_order_id,
                package_id=pkg.id,
                model_id=int(item.get("model_id") or pkg.model_id),
                brand_id=pkg.brand_id,
                collection_id=pkg.collection_id,
                color=item["color"],
                size=item["size"],
                quantity=qty,
                available_qty=qty,
                cost_per_piece=cost,
                warehouse_id=pkg.warehouse_id,
                status="available",
            )
        )


def _apply_package_edit_request(db: Session, request: PackageChangeRequest, user_id: int | None) -> Package:
    pkg = db.get(Package, request.package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    _ensure_package_can_change(db, pkg)

    target = request.payload_json or {}
    items = list(target.get("items") or [])
    allocations = list(target.get("batch_allocations") or [])
    if not items:
        raise HTTPException(400, "Edit request has no package items")
    if pkg.production_order_id is not None:
        _enforce_packaged_quantity_available(
            db,
            production_order_id=int(pkg.production_order_id),
            allocations=allocations,
            total=int(target["total_quantity"]),
            exclude_package_id=int(pkg.id),
        )

    previous_location = (pkg.storage_cell, pkg.storage_shelf)
    pkg.color = target["color"]
    pkg.package_type = target["package_type"]
    pkg.capacity = int(target["capacity"])
    pkg.weight_kg = target.get("weight_kg")
    pkg.warehouse_id = target.get("warehouse_id")
    pkg.storage_cell = target.get("storage_cell")
    pkg.storage_shelf = target.get("storage_shelf")
    pkg.notes = target.get("notes")
    pkg.production_batch_id = target.get("production_batch_id")
    pkg.total_quantity = int(target["total_quantity"])
    if pkg.storage_cell:
        next_location = (pkg.storage_cell, pkg.storage_shelf)
        if previous_location != next_location or not pkg.storage_placed_at:
            pkg.storage_placed_at = datetime.now(timezone.utc)
    else:
        pkg.storage_shelf = None
        pkg.storage_placed_at = None

    db.query(PackageItem).filter(PackageItem.package_id == pkg.id).delete(synchronize_session=False)
    db.query(PackageBatchAllocation).filter(PackageBatchAllocation.package_id == pkg.id).delete(synchronize_session=False)
    db.flush()

    for item in items:
        db.add(
            PackageItem(
                package_id=pkg.id,
                model_id=int(item.get("model_id") or pkg.model_id),
                color=item["color"],
                size=item["size"],
                quantity=int(item["quantity"]),
            )
        )
    for alloc in allocations:
        db.add(
            PackageBatchAllocation(
                package_id=pkg.id,
                production_batch_id=int(alloc["production_batch_id"]),
                quantity=int(alloc["quantity"]),
            )
        )

    _replace_finished_goods_for_package(db, pkg, items)
    db.add(
        PackageScanLog(
            package_id=pkg.id,
            scanned_by=user_id,
            scan_type="edit_approved",
            location=format_storage_location(pkg.storage_cell, pkg.storage_shelf),
        )
    )
    db.flush()
    _sync_package_production(db, pkg.production_order_id)
    return pkg


def _apply_package_delete_request(db: Session, request: PackageChangeRequest) -> None:
    pkg = db.get(Package, request.package_id)
    if not pkg:
        raise HTTPException(404, "Package not found")
    _ensure_package_can_change(db, pkg)
    production_order_id = pkg.production_order_id

    db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg.id).delete(synchronize_session=False)
    db.query(PackageScanLog).filter(PackageScanLog.package_id == pkg.id).delete(synchronize_session=False)
    db.query(PackageBatchAllocation).filter(PackageBatchAllocation.package_id == pkg.id).delete(synchronize_session=False)
    db.query(PackageItem).filter(PackageItem.package_id == pkg.id).delete(synchronize_session=False)
    db.flush()
    db.delete(pkg)
    db.flush()
    _sync_package_production(db, production_order_id)


def approve_package_change_request(
    db: Session,
    request: PackageChangeRequest,
    *,
    user_id: int | None,
    notes: str | None = None,
) -> PackageChangeRequest:
    if request.status != PACKAGE_CHANGE_PENDING_STATUS:
        raise HTTPException(400, f"Package change request is already {request.status}")

    if request.request_type == "edit":
        _apply_package_edit_request(db, request, user_id)
    elif request.request_type == "delete":
        _apply_package_delete_request(db, request)
    else:
        raise HTTPException(400, "Unknown package change request type")

    request.status = "approved"
    request.reviewed_by = user_id
    request.reviewed_at = datetime.now(timezone.utc)
    request.decision_notes = notes
    db.add(request)
    _notify_package_requester(
        db,
        request=request,
        title="Package change approved",
        message=f"{request.package_no} {request.request_type} request was approved.",
    )
    db.flush()
    return request


def reject_package_change_request(
    db: Session,
    request: PackageChangeRequest,
    *,
    user_id: int | None,
    notes: str | None = None,
) -> PackageChangeRequest:
    if request.status != PACKAGE_CHANGE_PENDING_STATUS:
        raise HTTPException(400, f"Package change request is already {request.status}")
    request.status = "rejected"
    request.reviewed_by = user_id
    request.reviewed_at = datetime.now(timezone.utc)
    request.decision_notes = notes
    db.add(request)
    _notify_package_requester(
        db,
        request=request,
        title="Package change rejected",
        message=f"{request.package_no} {request.request_type} request was rejected.",
    )
    db.flush()
    return request


def receive_at_storage(
    db: Session,
    pkg: Package,
    warehouse_id: int | None,
    user_id: int | None,
    *,
    storage_cell: str | None = None,
    storage_shelf: str | None = None,
):
    if pkg.status not in ("packed",):
        raise HTTPException(400, f"Package in status '{pkg.status}' cannot be received at storage")
    cell, shelf = validate_storage_location(storage_cell, storage_shelf, require_cell=False)
    pkg.status = "received_in_storage"
    pkg.received_by = user_id
    pkg.received_at = datetime.now(timezone.utc)
    if warehouse_id:
        pkg.warehouse_id = warehouse_id
    if cell:
        pkg.storage_cell = cell
        pkg.storage_shelf = shelf
        pkg.storage_placed_at = datetime.now(timezone.utc)
    db.add(
        PackageScanLog(
            package_id=pkg.id,
            scanned_by=user_id,
            scan_type="received_storage",
            location=format_storage_location(cell, shelf),
        )
    )
    _sync_package_production(db, pkg.production_order_id)
    db.flush()


def place_on_storage_map(
    db: Session,
    pkg: Package,
    *,
    storage_cell: str,
    storage_shelf: str | None,
    user_id: int | None,
):
    if pkg.status in ("shipped", "delivered", "damaged"):
        raise HTTPException(400, f"Package in status '{pkg.status}' cannot be moved on storage map")
    cell, shelf = validate_storage_location(storage_cell, storage_shelf, require_cell=True)
    prev_location = format_storage_location(pkg.storage_cell, pkg.storage_shelf)
    next_location = format_storage_location(cell, shelf)

    pkg.storage_cell = cell
    pkg.storage_shelf = shelf
    pkg.storage_placed_at = datetime.now(timezone.utc)

    scan_type = "placed_storage" if not prev_location else "relocated_storage"
    db.add(
        PackageScanLog(
            package_id=pkg.id,
            scanned_by=user_id,
            scan_type=scan_type,
            location=next_location,
        )
    )
    db.flush()


def reserve_package(db: Session, pkg: Package, user_id: int | None):
    if pkg.status not in ("received_in_storage", "packed"):
        raise HTTPException(400, f"Package cannot be reserved from status '{pkg.status}'")
    pkg.status = "reserved"
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="reserved"))
    _sync_package_production(db, pkg.production_order_id)
    db.flush()


def ship_package(db: Session, pkg: Package, user_id: int | None):
    if pkg.status not in ("received_in_storage", "reserved"):
        raise HTTPException(400, f"Package cannot be shipped from status '{pkg.status}'")
    pkg.status = "shipped"
    pkg.shipped_at = datetime.now(timezone.utc)
    pkg.storage_cell = None
    pkg.storage_shelf = None
    pkg.storage_placed_at = None
    decrement_finished_goods_for_package(db, pkg)
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="shipped"))
    _sync_package_production(db, pkg.production_order_id)
    db.flush()


def mark_delivered(db: Session, pkg: Package, user_id: int | None):
    if pkg.status != "shipped":
        raise HTTPException(400, f"Package not in 'shipped' status (was '{pkg.status}')")
    pkg.status = "delivered"
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="delivered"))
    _sync_package_production(db, pkg.production_order_id)
    db.flush()


def mark_damaged(db: Session, pkg: Package, user_id: int | None):
    pkg.status = "damaged"
    pkg.storage_cell = None
    pkg.storage_shelf = None
    pkg.storage_placed_at = None
    db.add(PackageScanLog(package_id=pkg.id, scanned_by=user_id, scan_type="audit_check", location="damaged"))
    _sync_package_production(db, pkg.production_order_id)
    db.flush()
