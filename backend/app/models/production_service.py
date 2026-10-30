"""Production service: build production orders and work orders, manage flow."""
from datetime import datetime, timezone
import math
import re
from typing import cast
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.schemas import (
    Brand, Department, Item, Model, ProductionBatch, ProductionOrder,
    SalesOrder, StockBatch, WorkOrder,
)
from app.core.signing import strip_signature
from app.models.numbering_service import next_production_order_no, next_usluga_order_no
from app.models.inventory_service import available_stock_for_batch, missing_material_reservation_for_cutting
from app.models.model_images_service import model_print_image_url
from app.libs.enums.production import ProductionSourceType, ProductionType, SewingFactoryCode, WorkOrderStatus
from app.libs.dto.production.production import (
    ProductionOrderItemIn,
    ProductionOrderMaterialIn,
    ProductionOrderPrintingAttachment,
)
from app.libs.types.production import (
    ProductionBatchCreateValues,
    ProductionOrderCreateValues,
    ProductionOrderItemCreateValues,
    ProductionOrderMaterialCreateValues,
    ProductionBatchInputValues,
    ProductionOrderItemInputValues,
    ProductionOrderPrintingAttachmentValues,
    WorkOrderCreateValues,
    WorkOrderInitialState,
)
from app.schemas.production.production_persistence import (
    add_work_orders,
    apply_initial_production_workflow_state,
    insert_production_batches as persist_production_batches,
    insert_production_order,
    insert_production_order_components,
)


# Department code -> operation
DEPT_OPS = [
    ("CUT", "cutting"),
    ("PRT", "printing"),
    ("SEW", "sewing"),
    ("PKG", "packaging"),
    ("FGS", "storage_transfer"),
]

WORK_ORDER_OPERATION_PERMISSIONS = {
    "cutting": {"cutting.records", "cutting.bundles", "planning.production"},
    "printing": {"printing.records", "planning.production"},
    "sewing": {"sewing.records", "sewing.bundles", "planning.production"},
    "packaging": {"packaging.records", "packaging.packages", "planning.production"},
    "storage_transfer": {
        "storage.items",
        "storage.receive",
        "storage.transfer",
        "storage.packages",
        "planning.production",
    },
}


_NUMERIC_SIZE_RANGE = re.compile(r"^\s*(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*$")
_MAX_ESTIMATED_MATERIAL_AMOUNT = 9_999_999_999.9999


def expand_production_size_range_items(
    items: list[ProductionOrderItemIn | ProductionOrderItemInputValues] | None,
) -> list[ProductionOrderItemInputValues]:
    """Expand apparel ranges such as 46-56 and preserve the exact item total."""
    expanded: list[ProductionOrderItemInputValues] = []
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


def _get_dept(db: Session, code: str) -> Department:
    dept = db.query(Department).filter(Department.code == code).first()
    if not dept:
        raise HTTPException(400, f"Department '{code}' not configured")
    return dept


def printing_attachments_for_storage(
    attachments: list[
        ProductionOrderPrintingAttachment | ProductionOrderPrintingAttachmentValues
    ] | None,
) -> list[ProductionOrderPrintingAttachmentValues]:
    """Persist bare storage paths; signed URLs are regenerated on read."""
    out: list[ProductionOrderPrintingAttachmentValues] = []
    for attachment in attachments or []:
        data = attachment.model_dump() if hasattr(attachment, "model_dump") else dict(attachment)
        if data.get("file_url"):
            data["file_url"] = strip_signature(data["file_url"])
        out.append(cast(ProductionOrderPrintingAttachmentValues, data))
    return out


def create_production_order(
    db: Session,
    *,
    production_type: ProductionType,
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
    materials: list[ProductionOrderMaterialIn] | None = None,
    printing_instructions: str | None = None,
    printing_attachments: list[ProductionOrderPrintingAttachmentValues] | None = None,
    destination_warehouse_id: int | None = None,
    items: list[ProductionOrderItemIn] | None = None,
    created_by: int | None = None,
    source_type: ProductionSourceType = ProductionSourceType.STANDARD,
    service_customer_name: str | None = None,
    service_customer_reference: str | None = None,
    service_material_description: str | None = None,
    service_material_usage_kg: float | None = None,
    service_material_notes: str | None = None,
) -> ProductionOrder:
    if production_type not in (ProductionType.CLIENT_ORDER, ProductionType.BRANDED_STOCK, ProductionType.SERVICE_ORDER):
        raise HTTPException(400, "Invalid production_type")
    production_type = ProductionType(production_type)
    source_type_value = str(source_type or ProductionSourceType.STANDARD.value).strip().lower()
    if source_type_value not in {member.value for member in ProductionSourceType}:
        raise HTTPException(400, "Invalid production source_type")
    source_type = ProductionSourceType(source_type_value)
    if (production_type is ProductionType.SERVICE_ORDER) != (source_type is ProductionSourceType.USLUGA):
        raise HTTPException(400, "service_order and usluga source_type must be used together")

    # Usluga model labels such as "40-42" represent one paired garment size,
    # not shorthand for multiple independent sizes. Keep them byte-for-byte
    # aligned with the model so Cutting and its bundle passports use the same
    # size identity. Standard production retains its established range split.
    normalized_items = (
        list(items or [])
        if source_type is ProductionSourceType.USLUGA
        else [
            ProductionOrderItemIn.model_validate(row)
            for row in expand_production_size_range_items(
                [item.model_dump() for item in (items or [])]
            )
        ]
    )

    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if source_type is ProductionSourceType.USLUGA:
        if model.catalog_scope != "usluga" or model.factory_code != "ECO":
            raise HTTPException(400, "Usluga production requires an Eco Cotton Usluga model")
        if not str(service_customer_name or "").strip():
            raise HTTPException(400, "Usluga customer/company is required")
        if fabric_batch_id is not None or materials:
            raise HTTPException(400, "Usluga material must not be linked to inventory")
    elif model.catalog_scope != ProductionSourceType.STANDARD.value:
        raise HTTPException(404, "Model not found")
    if production_type is ProductionType.BRANDED_STOCK and model.status != "approved":
        raise HTTPException(400, "Branded stock production requires an approved model")
    if production_type is ProductionType.CLIENT_ORDER and not sales_order_id:
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

    normalized_materials: list[ProductionOrderMaterialCreateValues] = []
    selected_material_refs: list[tuple[StockBatch, Item]] = []
    seen_batch_ids: set[int] = set()
    for index, raw in enumerate(materials or [], start=1):
        try:
            batch_id = int(raw.stock_batch_id or 0)
            quantity = float(raw.estimated_quantity or 0)
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
        unit = str(raw.unit or batch.unit or item.unit or "kg").strip()
        if not unit:
            raise HTTPException(400, f"Material #{index} requires a unit")
        seen_batch_ids.add(batch_id)
        normalized_materials.append(ProductionOrderMaterialCreateValues(
            stock_batch_id=batch_id,
            estimated_quantity=quantity,
            unit=unit,
            position=index,
        ))
        selected_material_refs.append((batch, item))

    if normalized_materials:
        primary_material = normalized_materials[0]
        fabric_batch_id = primary_material.stock_batch_id
        selected_fabric_batch, selected_fabric_item = selected_material_refs[0]
        material_code = selected_fabric_item.sku
        material_unit = primary_material.unit
        material_amount = float(primary_material.estimated_quantity)
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
            if (
                not math.isfinite(material_amount)
                or material_amount > _MAX_ESTIMATED_MATERIAL_AMOUNT
            ):
                raise HTTPException(422, "Estimated material amount exceeds storage limits")
            material_unit = material_unit or "kg"

    production_no = (
        next_usluga_order_no(db)
        if source_type is ProductionSourceType.USLUGA
        else next_production_order_no(db)
    )
    print_notes = str(printing_instructions or "").strip() or None

    po = insert_production_order(db, ProductionOrderCreateValues(
        production_no=production_no,
        production_type=production_type,
        source_type=source_type,
        model_id=model_id,
        brand_id=selected_brand_id,
        fabric_batch_id=fabric_batch_id,
        sales_order_id=sales_order_id,
        planning_order_id=planning_order_id,
        collection_id=collection_id,
        planned_quantity=planned_quantity or sum(item.planned_quantity for item in normalized_items),
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
    ))

    item_values = [
        ProductionOrderItemCreateValues(
            model_id=int(item.model_id or model_id),
            color=item.color,
            size=item.size,
            planned_quantity=item.planned_quantity,
            printing_required=bool(item.printing_required) or (
                source_type is ProductionSourceType.STANDARD
                and bool(model_print_image_url(db.get(Model, item.model_id or model_id)))
            ),
        )
        for item in normalized_items
    ]
    insert_production_order_components(db, int(po.id), normalized_materials, item_values)
    return po


def create_production_batches(
    db: Session,
    production_order_id: int,
    batches: list[ProductionBatchInputValues] | None,
) -> list[ProductionBatch]:
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
    created: list[ProductionBatchCreateValues] = []
    for idx, raw in enumerate(batches, start=1):
        raw_quantity = raw.get("planned_quantity", 0)
        if isinstance(raw_quantity, bool):
            raise HTTPException(400, f"Batch #{idx} planned_quantity must be an integer")
        try:
            qty = int(raw_quantity)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(400, f"Batch #{idx} planned_quantity must be an integer") from None
        if not isinstance(raw_quantity, str) and raw_quantity != qty:
            raise HTTPException(400, f"Batch #{idx} planned_quantity must be an integer")
        if qty <= 0:
            raise HTTPException(400, f"Batch #{idx} planned_quantity must be > 0")
        if qty > 2_147_483_647:
            raise HTTPException(400, f"Batch #{idx} planned_quantity exceeds the supported maximum")

    for idx, raw in enumerate(batches, start=1):
        qty = int(raw.get("planned_quantity", 0))
        proposed_no = f"{int(po.id):04d}-{idx:02d}"
        batch_no = proposed_no
        suffix = 2
        while batch_no.lower() in used_nos:
            batch_no = f"{proposed_no}-{suffix}"
            suffix += 1
        used_nos.add(batch_no.lower())

        created.append(ProductionBatchCreateValues(
            batch_no=batch_no,
            batch_index=idx,
            name=(str(raw.get("name") or "").strip() or f"Nastil {idx}"),
            planned_quantity=qty,
            start_date=raw.get("start_date"),
            deadline=raw.get("deadline"),
            notes=(str(raw.get("notes") or "").strip() or None),
        ))

    return persist_production_batches(db, po.id, created)


def create_work_orders(
    db: Session,
    production_order_id: int,
    include_printing: bool = False,
    cutting_department_code: str = "CUT",
    factory_code: SewingFactoryCode | str = SewingFactoryCode.MILANA,
    sewing_factory_code: SewingFactoryCode | str | None = None,
    include_storage_transfer: bool = True,
) -> list[WorkOrder]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    include_printing = include_printing or any(item.printing_required for item in po.items) or (
        po.source_type == ProductionSourceType.STANDARD.value
        and bool(model_print_image_url(db.get(Model, po.model_id)))
    )
    existing_ops = {
        str(wo.operation)
        for wo in db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()
    }
    create_values: list[WorkOrderCreateValues] = []
    planned_qty = int(po.planned_quantity or 0)

    # Keep one WO per operation even when the PO has internal batches.
    # Batches are managed inside the operation screen, not by duplicating WOs.
    factory_value = str(factory_code or SewingFactoryCode.MILANA.value).strip().upper()
    try:
        normalized_factory = SewingFactoryCode(factory_value)
    except ValueError:
        raise HTTPException(400, "Factory must be MIL, BST, or ECO")
    sewing_factory_value = str(sewing_factory_code or normalized_factory.value).strip().upper()
    try:
        normalized_sewing_factory = SewingFactoryCode(sewing_factory_value)
    except ValueError:
        raise HTTPException(400, "Sewing factory must be MIL, BST, or ECO")
    normalized_cutting_code = str(
        cutting_department_code or (
            "ECT" if normalized_factory is SewingFactoryCode.ECO_COTTON else "CUT"
        )
    ).strip().upper()
    if normalized_cutting_code not in {"CUT", "ECT"}:
        raise HTTPException(400, f"Unsupported cutting department '{cutting_department_code}'")

    department_by_operation = {
        "cutting": normalized_cutting_code,
        "printing": "PRT",
        "sewing": normalized_sewing_factory.value,
        "packaging": {
            SewingFactoryCode.MILANA.value: "PKG",
            SewingFactoryCode.BESTTEX.value: "BPK",
            SewingFactoryCode.ECO_COTTON.value: "ECP",
        }[normalized_factory.value],
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
        create_values.append(WorkOrderCreateValues(
            department_id=dept.id,
            operation=op,
            status=WorkOrderStatus.WAITING,
            planned_input_qty=planned_qty,
            planned_output_qty=planned_qty,
            deadline=po.deadline,
        ))
        existing_ops.add(op)

    created = add_work_orders(db, int(po.id), create_values)

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
        reservation_missing = (
            po.source_type != ProductionSourceType.USLUGA.value
            and missing_material_reservation_for_cutting(db, int(po.id))
        )
        # Start only one cutting WO when there are duplicates from legacy data.
        first_started = False
        state_changes: list[tuple[WorkOrder, WorkOrderInitialState]] = []
        for cutting_wo in cutting_wos:
            if cutting_wo.status in (
                WorkOrderStatus.NEW,
                WorkOrderStatus.PLANNING,
                WorkOrderStatus.WAITING,
            ):
                if not first_started and not reservation_missing:
                    start_time = cutting_wo.start_time or datetime.now(timezone.utc)
                    state_changes.append((cutting_wo, WorkOrderInitialState(
                        work_order_id=int(cutting_wo.id),
                        status=WorkOrderStatus.IN_PROGRESS,
                        start_time=start_time,
                        set_start_time=True,
                    )))
                    first_started = True
                else:
                    state_changes.append((cutting_wo, WorkOrderInitialState(
                        work_order_id=int(cutting_wo.id),
                        status=WorkOrderStatus.WAITING,
                        start_time=None,
                        set_start_time=False,
                    )))
            elif cutting_wo.status in (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.PAUSED):
                first_started = True
        po_status = "planning" if reservation_missing and not first_started else "cutting"
    else:
        state_changes = []
        po_status = "planning"
    apply_initial_production_workflow_state(db, po, po_status, state_changes)
    return created
