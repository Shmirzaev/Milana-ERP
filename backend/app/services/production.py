"""Production service: build production orders and work orders, manage flow."""
from datetime import datetime, timezone
import re
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Brand, Department, Item, Model, ProductionBatch, ProductionOrder,
    ProductionOrderItem, ProductionOrderMaterial, SalesOrder, StockBatch, WorkOrder,
)
from app.core.signing import strip_signature
from app.services.numbering import next_production_order_no, next_usluga_order_no
from app.services.inventory import available_stock_for_batch, missing_material_reservation_for_cutting


# Department code -> operation
DEPT_OPS = [
    ("CUT", "cutting"),
    ("PRT", "printing"),
    ("SEW", "sewing"),
    ("PKG", "packaging"),
    ("FGS", "storage_transfer"),
]

_NUMERIC_SIZE_RANGE = re.compile(r"^\s*(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*$")


def expand_production_size_range_items(items: list[dict] | None) -> list[dict]:
    """Expand apparel ranges such as 46-56 and preserve the exact item total."""
    expanded: list[dict] = []
    for raw in items or []:
        item = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        size = str(item.get("size") or "").strip()
        match = _NUMERIC_SIZE_RANGE.fullmatch(size)
        if not match:
            expanded.append(item)
            continue

        first, last = (int(value) for value in match.groups())
        if first > last or (last - first) % 2 or (last - first) // 2 > 50:
            expanded.append(item)
            continue

        sizes = [str(value) for value in range(first, last + 1, 2)]
        quantity = max(0, int(item.get("planned_quantity") or 0))
        if len(sizes) <= 1 or quantity < len(sizes):
            expanded.append(item)
            continue

        per_size, remainder = divmod(quantity, len(sizes))
        for index, value in enumerate(sizes):
            row = dict(item)
            row["size"] = value
            row["planned_quantity"] = per_size + (1 if index < remainder else 0)
            expanded.append(row)
    return expanded


def _fit_production_no(value: str, suffix: str = "") -> str:
    max_len = 64
    if len(value) + len(suffix) <= max_len:
        return f"{value}{suffix}"
    return f"{value[: max_len - len(suffix)]}{suffix}"


def _production_no_for_sales_order(db: Session, so: SalesOrder) -> str:
    base = str(so.order_no)
    index = 1
    while True:
        candidate = base if index == 1 else _fit_production_no(base, f"-{index}")
        existing = db.query(ProductionOrder.id).filter(ProductionOrder.production_no == candidate).first()
        if not existing:
            return candidate
        index += 1


def _get_dept(db: Session, code: str) -> Department:
    dept = db.query(Department).filter(Department.code == code).first()
    if not dept:
        raise HTTPException(400, f"Department '{code}' not configured")
    return dept


def printing_attachments_for_storage(attachments) -> list[dict]:
    """Persist bare storage paths; signed URLs are regenerated on read."""
    out: list[dict] = []
    for attachment in attachments or []:
        data = attachment.model_dump() if hasattr(attachment, "model_dump") else dict(attachment)
        if data.get("file_url"):
            data["file_url"] = strip_signature(data["file_url"])
        out.append(data)
    return out


def create_production_order(
    db: Session,
    *,
    production_type: str,
    model_id: int,
    brand_id: int | None = None,
    fabric_batch_id: int | None = None,
    sales_order_id: int | None = None,
    planning_order_id: int | None = None,
    collection_id: int | None = None,
    planned_quantity: int = 0,
    start_date: datetime | None = None,
    deadline: datetime | None = None,
    estimated_material_code: str | None = None,
    estimated_material_amount: float | None = None,
    estimated_material_unit: str | None = None,
    materials: list[dict] | None = None,
    printing_instructions: str | None = None,
    printing_attachments: list[dict] | None = None,
    destination_warehouse_id: int | None = None,
    items: list[dict] | None = None,
    created_by: int | None = None,
    source_type: str = "standard",
    service_customer_name: str | None = None,
    service_customer_reference: str | None = None,
    service_material_description: str | None = None,
    service_material_usage_kg: float | None = None,
    service_material_notes: str | None = None,
) -> ProductionOrder:
    if production_type not in ("client_order", "branded_stock", "service_order"):
        raise HTTPException(400, "Invalid production_type")
    source_type = str(source_type or "standard").strip().lower()
    if source_type not in {"standard", "usluga"}:
        raise HTTPException(400, "Invalid production source_type")
    if (production_type == "service_order") != (source_type == "usluga"):
        raise HTTPException(400, "service_order and usluga source_type must be used together")

    # Usluga model labels such as "40-42" represent one paired garment size,
    # not shorthand for multiple independent sizes. Keep them byte-for-byte
    # aligned with the model so Cutting and its bundle passports use the same
    # size identity. Standard production retains its established range split.
    normalized_items = (
        [raw.model_dump() if hasattr(raw, "model_dump") else dict(raw) for raw in (items or [])]
        if source_type == "usluga"
        else expand_production_size_range_items(items)
    )

    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if source_type == "usluga":
        if model.catalog_scope != "usluga" or model.factory_code != "ECO":
            raise HTTPException(400, "Usluga production requires an Eco Cotton Usluga model")
        if not str(service_customer_name or "").strip():
            raise HTTPException(400, "Usluga customer/company is required")
        if fabric_batch_id is not None or materials:
            raise HTTPException(400, "Usluga material must not be linked to inventory")
    elif model.catalog_scope != "standard":
        raise HTTPException(404, "Model not found")
    if production_type == "branded_stock" and model.status != "approved":
        raise HTTPException(400, "Branded stock production requires an approved model")
    if production_type == "client_order" and not sales_order_id:
        raise HTTPException(400, "Client order production requires sales_order_id")

    so = None
    if sales_order_id:
        so = db.get(SalesOrder, sales_order_id)
        if not so:
            raise HTTPException(404, "Sales order not found")

    sales_brand_id = so.items[0].brand_id if so and so.items else None
    selected_brand_id = brand_id or sales_brand_id or model.brand_id
    if selected_brand_id:
        brand = db.get(Brand, selected_brand_id)
        if not brand:
            raise HTTPException(404, "Brand not found")
        if not brand.is_active:
            raise HTTPException(400, "Brand is inactive")

    normalized_materials: list[dict] = []
    seen_batch_ids: set[int] = set()
    for index, raw in enumerate(materials or [], start=1):
        row = raw.model_dump() if hasattr(raw, "model_dump") else dict(raw)
        try:
            batch_id = int(row.get("stock_batch_id") or 0)
            quantity = float(row.get("estimated_quantity") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Material #{index} has an invalid batch or quantity")
        if batch_id <= 0:
            raise HTTPException(400, f"Material #{index} requires an inventory batch")
        if quantity <= 0:
            raise HTTPException(400, f"Material #{index} estimated quantity must be greater than zero")
        if batch_id in seen_batch_ids:
            raise HTTPException(400, "The same fabric batch cannot be added more than once")
        batch = db.get(StockBatch, batch_id)
        if not batch:
            raise HTTPException(404, f"Material #{index} inventory batch not found")
        item = db.get(Item, batch.item_id)
        if not item or str(item.category or "").lower() not in {"fabric", "semi_finished"}:
            raise HTTPException(400, f"Material #{index} is not a fabric inventory batch")
        if available_stock_for_batch(db, int(batch.id)) <= 0:
            raise HTTPException(400, f"Material #{index} batch has no available stock")
        unit = str(row.get("unit") or batch.unit or item.unit or "kg").strip()
        if not unit:
            raise HTTPException(400, f"Material #{index} requires a unit")
        seen_batch_ids.add(batch_id)
        normalized_materials.append({
            "stock_batch_id": batch_id,
            "estimated_quantity": quantity,
            "unit": unit,
            "batch": batch,
            "item": item,
        })

    if normalized_materials:
        primary_material = normalized_materials[0]
        fabric_batch_id = int(primary_material["stock_batch_id"])
        selected_fabric_batch = primary_material["batch"]
        selected_fabric_item = primary_material["item"]
        material_code = selected_fabric_item.sku
        material_unit = primary_material["unit"]
        material_amount = float(primary_material["estimated_quantity"])
    else:
        selected_fabric_batch = db.get(StockBatch, fabric_batch_id) if fabric_batch_id else None
        if fabric_batch_id and not selected_fabric_batch:
            raise HTTPException(404, "Fabric inventory batch not found")
        if selected_fabric_batch:
            selected_fabric_item = db.get(Item, selected_fabric_batch.item_id)
            if not selected_fabric_item or str(selected_fabric_item.category or "").lower() not in {
                "fabric", "semi_finished",
            }:
                raise HTTPException(400, "Selected inventory batch is not fabric")
            if available_stock_for_batch(db, int(selected_fabric_batch.id)) <= 0:
                raise HTTPException(400, "Selected fabric batch has no available stock")
            material_code = selected_fabric_item.sku
            material_unit = selected_fabric_batch.unit or selected_fabric_item.unit
        else:
            material_code = str(estimated_material_code or "").strip() or None
            material_unit = str(estimated_material_unit or "").strip() or None

        material_amount = None
        if estimated_material_amount is not None:
            material_amount = float(estimated_material_amount)
            if material_amount < 0:
                raise HTTPException(400, "Estimated material amount cannot be negative")
            material_unit = material_unit or "kg"

    production_no = (
        _production_no_for_sales_order(db, so)
        if so
        else next_usluga_order_no(db)
        if source_type == "usluga"
        else next_production_order_no(db)
    )
    print_notes = str(printing_instructions or "").strip() or None

    po = ProductionOrder(
        production_no=production_no,
        production_type=production_type,
        source_type=source_type,
        sales_order_id=sales_order_id,
        planning_order_id=planning_order_id,
        collection_id=collection_id,
        model_id=model_id,
        brand_id=selected_brand_id,
        fabric_batch_id=fabric_batch_id,
        status="new",
        planned_quantity=planned_quantity or sum(int(i.get("planned_quantity", 0)) for i in normalized_items),
        start_date=start_date,
        deadline=deadline,
        estimated_material_code=material_code,
        estimated_material_amount=material_amount,
        estimated_material_unit=material_unit,
        printing_instructions=print_notes,
        printing_attachments=printing_attachments or [],
        destination_warehouse_id=destination_warehouse_id,
        service_customer_name=str(service_customer_name or "").strip() or None,
        service_customer_reference=str(service_customer_reference or "").strip() or None,
        service_material_description=str(service_material_description or "").strip() or None,
        service_material_usage_kg=service_material_usage_kg,
        service_material_notes=str(service_material_notes or "").strip() or None,
        created_by=created_by,
    )
    db.add(po)
    db.flush()

    for position, row in enumerate(normalized_materials, start=1):
        db.add(ProductionOrderMaterial(
            production_order_id=po.id,
            stock_batch_id=row["stock_batch_id"],
            estimated_quantity=row["estimated_quantity"],
            unit=row["unit"],
            position=position,
        ))

    for it in normalized_items:
        db.add(ProductionOrderItem(
            production_order_id=po.id,
            model_id=it.get("model_id", model_id),
            color=it["color"],
            size=it["size"],
            planned_quantity=int(it.get("planned_quantity", 0)),
            printing_required=bool(it.get("printing_required")),
        ))
    db.flush()
    return po


def create_production_batches(db: Session, production_order_id: int, batches: list[dict] | None) -> list[ProductionBatch]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    if not batches:
        return []

    # Do not silently create duplicate batches for idempotent endpoint retries.
    existing = db.query(ProductionBatch).filter(ProductionBatch.production_order_id == po.id).all()
    if existing:
        return existing

    used_nos: set[str] = set()
    created: list[ProductionBatch] = []
    for idx, raw in enumerate(batches, start=1):
        qty = int(raw.get("planned_quantity", 0))
        if qty <= 0:
            raise HTTPException(400, f"Batch #{idx} planned_quantity must be > 0")

    for idx, raw in enumerate(batches, start=1):
        qty = int(raw.get("planned_quantity", 0))
        proposed_no = f"{int(po.id):04d}-{idx:02d}"
        batch_no = proposed_no
        suffix = 2
        while batch_no.lower() in used_nos:
            batch_no = f"{proposed_no}-{suffix}"
            suffix += 1
        used_nos.add(batch_no.lower())

        b = ProductionBatch(
            production_order_id=po.id,
            batch_no=batch_no,
            batch_index=idx,
            name=(str(raw.get("name") or "").strip() or None),
            planned_quantity=qty,
            start_date=raw.get("start_date"),
            deadline=raw.get("deadline"),
            notes=(str(raw.get("notes") or "").strip() or None),
        )
        db.add(b)
        created.append(b)

    db.flush()
    return created


def create_work_orders(
    db: Session,
    production_order_id: int,
    include_printing: bool = False,
    cutting_department_code: str = "CUT",
    factory_code: str = "MIL",
    sewing_factory_code: str | None = None,
    include_storage_transfer: bool = True,
) -> list[WorkOrder]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    existing_ops = {
        str(wo.operation)
        for wo in db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()
    }
    created: list[WorkOrder] = []
    planned_qty = int(po.planned_quantity or 0)

    # Keep one WO per operation even when the PO has internal batches.
    # Batches are managed inside the operation screen, not by duplicating WOs.
    normalized_factory = str(factory_code or "MIL").strip().upper()
    if normalized_factory not in {"MIL", "BST", "ECO"}:
        raise HTTPException(400, "Factory must be MIL, BST, or ECO")
    normalized_sewing_factory = str(sewing_factory_code or normalized_factory).strip().upper()
    if normalized_sewing_factory not in {"MIL", "BST", "ECO"}:
        raise HTTPException(400, "Sewing factory must be MIL, BST, or ECO")
    normalized_cutting_code = str(cutting_department_code or ("ECT" if normalized_factory == "ECO" else "CUT")).strip().upper()
    if normalized_cutting_code not in {"CUT", "ECT"}:
        raise HTTPException(400, f"Unsupported cutting department '{cutting_department_code}'")

    department_by_operation = {
        "cutting": normalized_cutting_code,
        "printing": "PRT",
        "sewing": normalized_sewing_factory,
        "packaging": {"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}[normalized_factory],
        "storage_transfer": "FGS",
    }

    for code, op in DEPT_OPS:
        if op == "printing" and not include_printing:
            continue
        if op == "storage_transfer" and not include_storage_transfer:
            continue
        if op in existing_ops:
            continue
        dept = _get_dept(db, department_by_operation[op])
        wo = WorkOrder(
            production_order_id=po.id,
            production_batch_id=None,
            department_id=dept.id,
            operation=op,
            status="waiting",
            planned_input_qty=planned_qty,
            planned_output_qty=planned_qty,
            deadline=po.deadline,
        )
        db.add(wo)
        created.append(wo)
        existing_ops.add(op)

    # Orders should enter cutting immediately; planning only assigns sewing lines.
    cutting_wos = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.production_order_id == po.id,
            WorkOrder.operation == "cutting",
        )
        .order_by(WorkOrder.production_batch_id.asc(), WorkOrder.id.asc())
        .all()
    )
    if cutting_wos:
        reservation_missing = po.source_type != "usluga" and missing_material_reservation_for_cutting(db, int(po.id))
        # Start only one cutting WO when there are duplicates from legacy data.
        first_started = False
        for cutting_wo in cutting_wos:
            if cutting_wo.status in ("new", "planning", "waiting"):
                if not first_started and not reservation_missing:
                    cutting_wo.status = "in_progress"
                    if not cutting_wo.start_time:
                        cutting_wo.start_time = datetime.now(timezone.utc)
                    first_started = True
                else:
                    cutting_wo.status = "waiting"
            elif cutting_wo.status in ("in_progress", "paused"):
                first_started = True
        po.status = "planning" if reservation_missing and not first_started else "cutting"
    else:
        po.status = "planning"
    db.flush()
    return created
