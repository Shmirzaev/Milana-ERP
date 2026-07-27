import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.deps import DbSession, PRODUCTION_READ_PERMISSIONS, require_permissions, is_admin
from app.core.signing import sign_path
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    extension_for_upload,
    read_validated_upload_content,
    safe_content_type,
)
from app.models import (
    ProductionOrder, WorkOrder, CuttingRecord, PrintingRecord, SewingRecord, SewingReplacementRequest,
    PackagingRecord, PackagingReceipt,
    SalesOrder, QualityCheck, User, Department, SewingFlow, SewingAssignment, Package, PackageBatchAllocation,
    ProductionBatch, WasteRecord,
    ProductionOrderItem, Bundle, Item, Model, ModelBOM, StockBatch,
)
from app.schemas.inventory import MaterialReservationOut, MaterialReservationStatusOut
from app.schemas.production import (
    ProductionOrderIn, ProductionOrderOut, ProductionOrderDetail,
    WorkOrderOut, WorkOrderUpdate,
    CuttingRecordIn, PrintingRecordIn, SewingRecordIn, PackagingRecordIn,
    QualityCheckIn, QualityCheckOut,
)
from app.core.dt import as_utc
from app.services.audit import log_action
from app.services.production import (
    create_production_order,
    create_production_batches,
    create_work_orders,
    printing_attachments_for_storage,
)
from app.services.inventory import (
    auto_reserve_materials_for_production_order,
    consume_material_reservations_for_stock_batch,
    ensure_accessories_issued_for_sewing,
    material_reservation_status_for_production_order,
    missing_material_reservation_for_cutting,
    require_material_reservation_before_cutting,
    sync_sewing_accessory_block,
)
from app.services.bundles import (
    create_bundle,
    is_sewing_department_code,
    resolve_sewing_factory_code,
    sewing_department_code_for_bundle_route,
    sync_textile_departments_for_bundle_route,
    sync_packaging_department_for_bundle_route,
)
from app.services.workflow import (
    WORKFLOW_SEQUENCE,
    advance_workflow,
    consume_packaging_materials_from_bom,
    consume_stock_batch,
    create_waste_record,
    notify_department,
    processed_work_order_qty,
    propagate_cutting_plan_from_output,
    sync_production_order_status,
)
from app.services.model_images import (
    material_preview_image_url,
    model_preview_image_url,
    model_variant_picture_url,
)
from app.services.cutting_sheet import render_cutting_sheet_html

router = APIRouter(tags=["production"])

# Anyone who legitimately runs the production floor: planners plus the four
# stage operator roles (and admins). Blocks unrelated staff (HR, Finance, Sales)
# from mutating work orders / quality records that aren't theirs.
_PRODUCTION_FLOOR_PERMS = (
    "planning.production",
    "sewing.flows",
    "cutting.records",
    "printing.records",
    "sewing.records",
    "packaging.records",
    "management.approve",
    "*",
)

_ACTIVE_WO_STATUSES = ("waiting", "pending", "collected", "ready", "in_progress", "paused", "new", "planning")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")
_PRE_CUTTING_EDIT_STATUSES = ("new", "planning", "pending", "waiting", "ready")
_PO_PRE_CUTTING_EDIT_FIELDS = {
    "model_id",
    "sales_order_id",
    "planned_quantity",
    "deadline",
    "estimated_material_code",
    "estimated_material_amount",
    "estimated_material_unit",
}


def _notify_accessory_issue_block(db: DbSession, wo: WorkOrder, plan: dict, stage: str) -> None:
    summary = plan.get("summary") or {}
    remaining = float(summary.get("remaining_quantity") or 0)
    shortage = float(summary.get("shortage") or 0)
    order_ref = wo.order_no or wo.id
    message = (
        f"Order {order_ref} needs accessory issue before sewing. "
        f"Remaining {remaining:g}; shortage {shortage:g}."
    )
    notify_department(
        db,
        department_code="STR",
        title="Accessories required before sewing",
        message=message,
        link=f"/inventory?group=accessories&q={order_ref}",
    )
    notify_department(
        db,
        department_code="PLN",
        title=f"Sewing blocked after {stage}",
        message=message,
        link=f"/production-orders/{wo.production_order_id}",
    )


class PrintingCollectIn(BaseModel):
    deadline: datetime
    notes: str | None = None


class SplitBatchLineIn(BaseModel):
    name: str | None = None
    planned_quantity: int
    start_date: datetime | None = None
    deadline: datetime | None = None
    notes: str | None = None


class SplitWorkOrderBatchesIn(BaseModel):
    batches: list[SplitBatchLineIn]


class ExtraCuttingBatchIn(SplitBatchLineIn):
    pass


class ProductionOrderBreakdownLineIn(BaseModel):
    id: int | None = None
    color: str
    size: str
    planned_quantity: int
    printing_required: bool | None = None


class ProductionOrderBreakdownUpdateIn(BaseModel):
    items: list[ProductionOrderBreakdownLineIn]


class CuttingBundleQuantityRowIn(BaseModel):
    id: int
    quantity: int


class CuttingBundleQuantityUpdateIn(BaseModel):
    bundles: list[CuttingBundleQuantityRowIn]


class ProductionOrderAutoReservationIn(BaseModel):
    mode: str = "full_remaining"
    reserve_accessories: bool = True
    reserve_materials: bool = True
    reserve_packaging: bool = True


class PackagingReceiveFromSewingIn(BaseModel):
    bundle_code: str | None = None
    work_order_id: int | None = None
    production_batch_id: int | None = None
    quantity: int | None = None
    notes: str | None = None


def _material_reservation_payload(reservation) -> dict:
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


def _material_reservation_status_payload(db: DbSession, production_order_id: int) -> dict:
    status = material_reservation_status_for_production_order(db, production_order_id)
    return {
        **status,
        "reservations": [_material_reservation_payload(row) for row in status["reservations"]],
    }


def _sign_printing_attachment_urls(payload: dict) -> dict:
    for attachment in payload.get("printing_attachments") or []:
        if isinstance(attachment, dict) and attachment.get("file_url"):
            attachment["file_url"] = sign_path(attachment["file_url"])
    return payload


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


def _estimated_material_composition(db: DbSession, material_code: str | None) -> list[dict]:
    code = str(material_code or "").strip()
    if not code:
        return []
    item = db.query(Item).filter(Item.sku == code).first()
    return _item_composition(item)


def _ordered_batches_for_work_order(db: DbSession, wo: WorkOrder) -> tuple[ProductionOrder, list[ProductionBatch]]:
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    batches = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.production_order_id == po.id)
        .order_by(ProductionBatch.batch_index.asc(), ProductionBatch.id.asc())
        .all()
    )
    return po, batches


def _resolve_record_batch_id(
    db: DbSession,
    wo: WorkOrder,
    payload_batch_id: int | None,
    *,
    operation_name: str,
) -> int | None:
    normalized = int(payload_batch_id) if payload_batch_id else None

    # Legacy mode: one WO per batch (or explicitly batch-tied WO)
    if wo.production_batch_id is not None:
        expected = int(wo.production_batch_id)
        if normalized is not None and normalized != expected:
            raise HTTPException(400, f"This work order is bound to batch #{expected}")
        return expected

    po, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return None

    if normalized is None:
        raise HTTPException(400, f"Select a production batch for this {operation_name} record")

    exists = db.query(ProductionBatch.id).filter(
        ProductionBatch.id == normalized,
        ProductionBatch.production_order_id == po.id,
    ).first()
    if not exists:
        raise HTTPException(404, "Production batch not found for this production order")
    return normalized


def _context_work_order(db: DbSession, source_wo: WorkOrder, operation: str) -> WorkOrder | None:
    qry = db.query(WorkOrder).filter(
        WorkOrder.production_order_id == source_wo.production_order_id,
        WorkOrder.operation == operation,
    )
    if source_wo.production_batch_id is None:
        qry = qry.filter(WorkOrder.production_batch_id.is_(None))
    else:
        qry = qry.filter(WorkOrder.production_batch_id == source_wo.production_batch_id)
    return qry.order_by(WorkOrder.id.asc()).first()


def _replacement_scope_query(db: DbSession, wo: WorkOrder):
    qry = db.query(SewingReplacementRequest).filter(
        SewingReplacementRequest.production_order_id == wo.production_order_id,
    )
    if wo.production_batch_id is not None:
        qry = qry.filter(SewingReplacementRequest.production_batch_id == wo.production_batch_id)
    return qry


def _replacement_blocking_qty(db: DbSession, wo: WorkOrder) -> int:
    qry = _replacement_scope_query(db, wo)
    if wo.operation == "cutting":
        value = qry.with_entities(
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.cut_qty), 0)
        ).scalar()
    else:
        value = qry.with_entities(
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.replaced_qty), 0)
        ).scalar()
    return max(0, int(value or 0))


def _ensure_replacements_do_not_block_completion(db: DbSession, wo: WorkOrder) -> None:
    if wo.operation not in {"cutting", "sewing", "packaging", "storage_transfer"}:
        return
    remaining = _replacement_blocking_qty(db, wo)
    if remaining <= 0:
        return
    if wo.operation == "cutting":
        raise HTTPException(409, f"Cutting cannot close: {remaining} replacement piece(s) still need to be cut")
    raise HTTPException(409, f"Work order cannot close: {remaining} failed piece(s) are still waiting for replacement")


def _replacement_status_payload(db: DbSession, wo: WorkOrder) -> dict:
    requests = _replacement_scope_query(db, wo).order_by(SewingReplacementRequest.id).all()
    batch_ids = sorted({int(row.production_batch_id) for row in requests if row.production_batch_id is not None})
    batches = db.query(ProductionBatch).filter(ProductionBatch.id.in_(batch_ids)).all() if batch_ids else []
    batch_by_id = {int(batch.id): batch for batch in batches}

    def blank(batch_id: int | None) -> dict:
        batch = batch_by_id.get(int(batch_id)) if batch_id is not None else None
        return {
            "production_batch_id": batch_id,
            "batch_no": batch.batch_no if batch else None,
            "batch_name": batch.name if batch else None,
            "requested_qty": 0,
            "waiting_cutting_qty": 0,
            "waiting_sewing_qty": 0,
            "replaced_qty": 0,
            "open_qty": 0,
        }

    total = blank(None)
    by_batch: dict[int | None, dict] = {}
    for request in requests:
        batch_id = int(request.production_batch_id) if request.production_batch_id is not None else None
        row = by_batch.setdefault(batch_id, blank(batch_id))
        requested = max(0, int(request.requested_qty or 0))
        cut = min(requested, max(0, int(request.cut_qty or 0)))
        replaced = min(requested, max(0, int(request.replaced_qty or 0)))
        waiting_cutting = max(0, requested - cut)
        waiting_sewing = max(0, cut - replaced)
        open_qty = max(0, requested - replaced)
        for target in (row, total):
            target["requested_qty"] += requested
            target["waiting_cutting_qty"] += waiting_cutting
            target["waiting_sewing_qty"] += waiting_sewing
            target["replaced_qty"] += replaced
            target["open_qty"] += open_qty
    return {
        "work_order_id": wo.id,
        "production_order_id": wo.production_order_id,
        **{key: value for key, value in total.items() if key not in {"production_batch_id", "batch_no", "batch_name"}},
        "items": list(by_batch.values()),
    }


def _upstream_work_order_for_start(db: DbSession, wo: WorkOrder) -> WorkOrder | None:
    try:
        operation_index = WORKFLOW_SEQUENCE.index(str(wo.operation))
    except ValueError:
        return None
    for operation in reversed(WORKFLOW_SEQUENCE[:operation_index]):
        upstream = _context_work_order(db, wo, operation)
        if upstream:
            return upstream
    return None


def _gate_record_submission(wo: WorkOrder) -> None:
    """Reject record submission when the work order is explicitly blocked."""
    if wo.is_blocked:
        raise HTTPException(409, f"Work order is blocked: {wo.block_reason or 'no reason given'}")


def _storage_received_total(db: DbSession, production_order_id: int) -> int:
    return int(
        db.query(func.coalesce(func.sum(Package.total_quantity), 0))
        .filter(
            Package.production_order_id == production_order_id,
            Package.status.in_(["received_in_storage", "reserved", "shipped", "delivered"]),
        )
        .scalar()
        or 0
    )


def _flow_committed_today(db: DbSession, flow_id: int, now: datetime) -> int:
    """Approximate today's committed load for a sewing line."""
    committed = 0

    # 1) Active split assignments contribute daily allocation.
    assignments = db.query(SewingAssignment).filter(
        SewingAssignment.sewing_flow_id == flow_id,
        SewingAssignment.status.in_(["planned", "in_progress"]),
    ).join(
        WorkOrder, WorkOrder.id == SewingAssignment.work_order_id,
    ).filter(
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    ).all()
    for a in assignments:
        remaining_qty = max(0, int(a.quantity or 0) - int(a.completed_qty or 0))
        if remaining_qty <= 0:
            continue
        a_start = as_utc(a.planned_start)
        a_end = as_utc(a.planned_end)
        if not a_start or not a_end:
            continue
        if a_start <= now <= a_end:
            days = max(1.0, (a_end - a_start).total_seconds() / 86400.0)
            committed += round(remaining_qty / days)

    # 2) Directly assigned sewing WOs (without split assignments) count fully.
    direct_wos = db.query(WorkOrder).filter(
        WorkOrder.sewing_flow_id == flow_id,
        WorkOrder.operation == "sewing",
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    ).all()
    for w in direct_wos:
        has_split = db.query(SewingAssignment.id).filter(
            SewingAssignment.work_order_id == w.id,
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).first()
        if has_split:
            continue
        remaining = max(0, int(w.planned_output_qty or 0) - int(w.passed_qty or 0))
        committed += remaining

    return int(committed)


# ===== Production Orders =====
@router.get("/production-orders", response_model=list[ProductionOrderOut])
def list_pos(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    status: str | None = None,
    production_type: str | None = None,
    page: int = 1,
    page_size: int = 50,
):
    qry = db.query(ProductionOrder).options(joinedload(ProductionOrder.sales_order))
    if status: qry = qry.filter(ProductionOrder.status == status)
    if production_type: qry = qry.filter(ProductionOrder.production_type == production_type)
    rows = qry.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    images_by_po = _work_order_images_by_po(db, [int(po.id) for po in rows])
    return [
        {
            **ProductionOrderOut.model_validate(po).model_dump(),
            **images_by_po.get(int(po.id), {}),
        }
        for po in rows
    ]


@router.post("/production-orders", response_model=ProductionOrderDetail, status_code=201)
def create_po(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type=payload.production_type,
        model_id=payload.model_id,
        brand_id=payload.brand_id,
        fabric_batch_id=payload.fabric_batch_id,
        sales_order_id=payload.sales_order_id,
        collection_id=payload.collection_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        estimated_material_code=payload.estimated_material_code,
        estimated_material_amount=payload.estimated_material_amount,
        estimated_material_unit=payload.estimated_material_unit,
        printing_instructions=payload.printing_instructions,
        printing_attachments=printing_attachments,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    if payload.batches:
        create_production_batches(db, po.id, [b.model_dump() for b in payload.batches])
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    include_printing = (
        any(bool(i.printing_required) for i in payload.items)
        or bool(str(payload.printing_instructions or "").strip())
        or bool(printing_attachments)
        or (any(bool(i.printing_required) for i in (so.items or [])) if so else False)
    )
    create_work_orders(
        db,
        po.id,
        include_printing=include_printing,
        cutting_department_code=payload.cutting_department_code,
    )
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no})
    db.commit(); db.refresh(po)
    return po


def _production_order_actuals(db: DbSession, production_order_id: int) -> dict[str, int]:
    bundle_count, bundle_qty = db.query(
        func.count(Bundle.id),
        func.coalesce(func.sum(Bundle.quantity), 0),
    ).filter(Bundle.production_order_id == production_order_id).one()

    cut_qty, bundled_qty_from_records = (
        db.query(
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.total_bundled_quantity), 0),
        )
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .one()
    )

    actual_bundle_quantity = int(bundle_qty or 0)
    if actual_bundle_quantity <= 0:
        actual_bundle_quantity = int(bundled_qty_from_records or 0)

    batch_plan_quantity = int(
        db.query(func.coalesce(func.sum(ProductionBatch.planned_quantity), 0))
        .filter(ProductionBatch.production_order_id == production_order_id)
        .scalar()
        or 0
    )
    actual_cut_quantity = int(cut_qty or 0)

    sewing_passed_quantity = int(
        db.query(func.coalesce(func.sum(SewingRecord.passed_qty), 0))
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .scalar()
        or 0
    )
    packaging_input_quantity, packaging_packed_quantity = (
        db.query(
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
        )
        .join(WorkOrder, WorkOrder.id == PackagingRecord.work_order_id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .one()
    )
    work_order_stage_quantities: list[int] = []
    for operation, actual_input_qty, actual_output_qty, passed_qty in (
        db.query(
            WorkOrder.operation,
            WorkOrder.actual_input_qty,
            WorkOrder.actual_output_qty,
            WorkOrder.passed_qty,
        )
        .filter(WorkOrder.production_order_id == production_order_id)
        .all()
    ):
        if operation == "packaging":
            work_order_stage_quantities.extend([actual_input_qty, actual_output_qty, passed_qty])
        elif operation in ("cutting", "printing", "sewing"):
            work_order_stage_quantities.extend([actual_output_qty, passed_qty])
    stage_actual_quantity = max(
        0,
        sewing_passed_quantity,
        int(packaging_input_quantity or 0),
        int(packaging_packed_quantity or 0),
        *(max(0, int(qty or 0)) for qty in work_order_stage_quantities),
    )

    return {
        "actual_quantity": max(actual_bundle_quantity, actual_cut_quantity, batch_plan_quantity, stage_actual_quantity),
        "actual_bundle_quantity": actual_bundle_quantity,
        "actual_bundle_count": int(bundle_count or 0),
        "actual_cut_quantity": actual_cut_quantity,
    }


def _planned_quantity_from_items(db: DbSession, production_order_id: int) -> int:
    return int(
        db.query(func.coalesce(func.sum(ProductionOrderItem.planned_quantity), 0))
        .filter(ProductionOrderItem.production_order_id == production_order_id)
        .scalar()
        or 0
    )


def _received_bundle_totals_by_po(db: DbSession, po_ids: list[int]) -> dict[int, dict[str, int]]:
    ids = sorted({int(po_id) for po_id in po_ids if po_id})
    if not ids:
        return {}

    rows = (
        db.query(
            Bundle.production_order_id,
            func.count(Bundle.id),
            func.coalesce(func.sum(Bundle.quantity), 0),
        )
        .filter(
            Bundle.production_order_id.in_(ids),
            Bundle.status == "received_sewing",
        )
        .group_by(Bundle.production_order_id)
        .all()
    )
    return {
        int(po_id): {
            "received_bundle_count": int(count or 0),
            "received_bundle_qty": int(qty or 0),
        }
        for po_id, count, qty in rows
    }


def _received_bundle_totals_by_scope(db: DbSession, po_ids: list[int]) -> dict[tuple[int, int | None], dict[str, int]]:
    ids = sorted({int(po_id) for po_id in po_ids if po_id})
    if not ids:
        return {}

    rows = (
        db.query(
            Bundle.production_order_id,
            Bundle.production_batch_id,
            func.count(Bundle.id),
            func.coalesce(func.sum(Bundle.quantity), 0),
        )
        .filter(
            Bundle.production_order_id.in_(ids),
            Bundle.status == "received_sewing",
        )
        .group_by(Bundle.production_order_id, Bundle.production_batch_id)
        .all()
    )
    return {
        (int(po_id), int(batch_id) if batch_id else None): {
            "received_bundle_count": int(count or 0),
            "received_bundle_qty": int(qty or 0),
        }
        for po_id, batch_id, count, qty in rows
    }


def _sewing_assignment_totals_by_scope(db: DbSession, wo_ids: list[int]) -> dict[tuple[int, int | None], int]:
    ids = sorted({int(wo_id) for wo_id in wo_ids if wo_id})
    if not ids:
        return {}

    rows = (
        db.query(
            SewingAssignment.work_order_id,
            SewingAssignment.production_batch_id,
            func.coalesce(func.sum(SewingAssignment.quantity), 0),
        )
        .filter(
            SewingAssignment.work_order_id.in_(ids),
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        )
        .group_by(SewingAssignment.work_order_id, SewingAssignment.production_batch_id)
        .all()
    )
    return {
        (int(wo_id), int(batch_id) if batch_id else None): int(qty or 0)
        for wo_id, batch_id, qty in rows
    }


def _batch_payload_fields(batch: ProductionBatch | None) -> dict:
    if not batch:
        return {
            "assignment_batch_id": None,
            "batch_no": None,
            "batch_name": None,
            "batch_index": None,
            "batch_planned_quantity": None,
        }
    return {
        "assignment_batch_id": int(batch.id),
        "batch_no": batch.batch_no,
        "batch_name": batch.name,
        "batch_index": int(batch.batch_index or 0) or None,
        "batch_planned_quantity": int(batch.planned_quantity or 0),
    }


def _work_order_images_by_po(db: DbSession, po_ids: list[int]) -> dict[int, dict[str, str | None]]:
    ids = sorted({int(po_id) for po_id in po_ids if po_id})
    if not ids:
        return {}

    po_model_rows = db.query(
        ProductionOrder.id,
        ProductionOrder.model_id,
        ProductionOrder.fabric_batch_id,
    ).filter(ProductionOrder.id.in_(ids)).all()
    model_ids = sorted({int(model_id) for _, model_id, _ in po_model_rows if model_id})
    fabric_batch_ids = sorted({int(batch_id) for _, _, batch_id in po_model_rows if batch_id})
    models = (
        db.query(Model)
        .options(
            joinedload(Model.images),
            joinedload(Model.bom).joinedload(ModelBOM.item),
            joinedload(Model.bom).joinedload(ModelBOM.stock_batch),
        )
        .filter(Model.id.in_(model_ids))
        .all()
        if model_ids
        else []
    )
    models_by_id = {int(model.id): model for model in models}
    fabric_batches_by_id = {
        int(batch.id): batch
        for batch in (db.query(StockBatch).filter(StockBatch.id.in_(fabric_batch_ids)).all() if fabric_batch_ids else [])
    }
    out: dict[int, dict[str, str | None]] = {}
    for po_id, model_id, fabric_batch_id in po_model_rows:
        model = models_by_id.get(int(model_id or 0))
        fabric_batch = fabric_batches_by_id.get(int(fabric_batch_id or 0))
        out[int(po_id)] = {
            "model_image_url": model_preview_image_url(model),
            "variant_picture_url": model_variant_picture_url(model),
            "material_image_url": (fabric_batch.image_url if fabric_batch else None) or material_preview_image_url(model),
        }
    return out


def _work_order_payload(
    wo: WorkOrder,
    received_by_po: dict[int, dict[str, int]] | None = None,
    images_by_po: dict[int, dict[str, str | None]] | None = None,
    *,
    received_override: dict[str, int] | None = None,
    extra: dict | None = None,
) -> dict:
    out = WorkOrderOut.model_validate(wo).model_dump()
    images = (images_by_po or {}).get(int(wo.production_order_id), {})
    out["model_image_url"] = images.get("model_image_url")
    out["variant_picture_url"] = images.get("variant_picture_url")
    out["material_image_url"] = images.get("material_image_url")
    if wo.operation == "sewing":
        received = received_override if received_override is not None else (received_by_po or {}).get(int(wo.production_order_id), {})
        out["received_bundle_count"] = int(received.get("received_bundle_count") or 0)
        out["received_bundle_qty"] = int(received.get("received_bundle_qty") or 0)
    if extra:
        out.update(extra)
    return out


def _received_sewing_work_order_payloads(
    db: DbSession,
    rows: list[WorkOrder],
    images_by_po: dict[int, dict[str, str | None]],
) -> list[dict]:
    po_ids = [int(w.production_order_id) for w in rows if w.operation == "sewing"]
    wo_ids = [int(w.id) for w in rows if w.operation == "sewing"]
    received_by_po = _received_bundle_totals_by_po(db, po_ids)
    received_by_scope = _received_bundle_totals_by_scope(db, po_ids)
    assigned_by_scope = _sewing_assignment_totals_by_scope(db, wo_ids)

    batches = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.production_order_id.in_(sorted(set(po_ids))))
        .order_by(ProductionBatch.production_order_id.asc(), ProductionBatch.batch_index.asc(), ProductionBatch.id.asc())
        .all()
        if po_ids
        else []
    )
    batches_by_po: dict[int, list[ProductionBatch]] = {}
    for batch in batches:
        batches_by_po.setdefault(int(batch.production_order_id), []).append(batch)

    out: list[dict] = []
    for wo in rows:
        po_id = int(wo.production_order_id)
        wo_id = int(wo.id)
        po_batches = batches_by_po.get(po_id, [])

        if wo.production_batch_id is not None:
            batch_id = int(wo.production_batch_id)
            batch = next((b for b in po_batches if int(b.id) == batch_id), None)
            received = received_by_scope.get((po_id, batch_id), {})
            received_qty = int(received.get("received_bundle_qty") or 0)
            if received_qty <= 0:
                continue
            assigned_qty = int(assigned_by_scope.get((wo_id, batch_id), 0))
            assignable_qty = max(0, received_qty - assigned_qty)
            if assignable_qty <= 0:
                continue
            out.append(
                _work_order_payload(
                    wo,
                    {},
                    images_by_po,
                    received_override=received,
                    extra={
                        **_batch_payload_fields(batch),
                        "production_batch_id": batch_id,
                        "planned_input_qty": int(batch.planned_quantity or 0) if batch else received_qty,
                        "planned_output_qty": int(batch.planned_quantity or 0) if batch else received_qty,
                        "deadline": batch.deadline if batch and batch.deadline else wo.deadline,
                        "assigned_qty": assigned_qty,
                        "assignable_qty": assignable_qty,
                    },
                )
            )
            continue

        if po_batches:
            unscoped_assigned_remaining = int(assigned_by_scope.get((wo_id, None), 0))
            for batch in po_batches:
                batch_id = int(batch.id)
                received = received_by_scope.get((po_id, batch_id), {})
                received_qty = int(received.get("received_bundle_qty") or 0)
                if received_qty <= 0:
                    continue
                direct_assigned_qty = int(assigned_by_scope.get((wo_id, batch_id), 0))
                unscoped_assigned_qty = min(max(0, unscoped_assigned_remaining), max(0, received_qty - direct_assigned_qty))
                unscoped_assigned_remaining = max(0, unscoped_assigned_remaining - unscoped_assigned_qty)
                assigned_qty = direct_assigned_qty + unscoped_assigned_qty
                assignable_qty = max(0, received_qty - assigned_qty)
                if assignable_qty <= 0:
                    continue
                out.append(
                    _work_order_payload(
                        wo,
                        {},
                        images_by_po,
                        received_override=received,
                        extra={
                            **_batch_payload_fields(batch),
                            "production_batch_id": batch_id,
                            "planned_input_qty": int(batch.planned_quantity or 0),
                            "planned_output_qty": int(batch.planned_quantity or 0),
                            "deadline": batch.deadline if batch.deadline else wo.deadline,
                            "assigned_qty": assigned_qty,
                            "assignable_qty": assignable_qty,
                        },
                    )
                )
            continue

        received = received_by_po.get(po_id, {})
        received_qty = int(received.get("received_bundle_qty") or 0)
        if received_qty <= 0:
            continue
        assigned_qty = int(assigned_by_scope.get((wo_id, None), 0))
        assignable_base = max(received_qty, int(wo.planned_input_qty or 0), int(wo.planned_output_qty or 0))
        assignable_qty = max(0, assignable_base - assigned_qty)
        if assignable_qty <= 0:
            continue
        out.append(
            _work_order_payload(
                wo,
                received_by_po,
                images_by_po,
                extra={
                    "assigned_qty": assigned_qty,
                    "assignable_qty": assignable_qty,
                },
            )
        )

    return out


def _project_original_plan_for_detail(
    db: DbSession,
    production_order_id: int,
    out: dict,
    actual_quantity: int | None = None,
) -> dict:
    item_plan_total = sum(max(0, int(row.get("planned_quantity") or 0)) for row in out.get("items") or [])
    if item_plan_total <= 0:
        item_plan_total = _planned_quantity_from_items(db, production_order_id)
    if item_plan_total <= 0:
        return out

    plan_qty = int(out.get("planned_quantity") or 0)
    if actual_quantity and actual_quantity != plan_qty:
        return out

    if plan_qty > item_plan_total:
        out["planned_quantity"] = item_plan_total

    for row in out.get("work_orders") or []:
        if int(row.get("planned_output_qty") or 0) > item_plan_total:
            row["planned_output_qty"] = item_plan_total
        if int(row.get("planned_input_qty") or 0) > item_plan_total:
            row["planned_input_qty"] = item_plan_total
    return out


def _production_order_detail_payload(db: DbSession, pid: int) -> dict:
    po = db.query(ProductionOrder).options(
        joinedload(ProductionOrder.sales_order),
        joinedload(ProductionOrder.batches),
        joinedload(ProductionOrder.items),
        joinedload(ProductionOrder.work_orders),
    ).filter(ProductionOrder.id == pid).first()
    if not po: raise HTTPException(404, "Production order not found")
    out = ProductionOrderDetail.model_validate(po).model_dump()
    out["estimated_material_composition"] = _estimated_material_composition(db, po.estimated_material_code)
    model = (
        db.query(Model)
        .options(
            joinedload(Model.images),
            joinedload(Model.bom).joinedload(ModelBOM.item),
            joinedload(Model.bom).joinedload(ModelBOM.stock_batch),
        )
        .filter(Model.id == po.model_id)
        .first()
    )
    out["model_image_url"] = model_preview_image_url(model)
    out["variant_picture_url"] = model_variant_picture_url(model)
    planned_fabric_batch = db.get(StockBatch, po.fabric_batch_id) if po.fabric_batch_id else None
    out["material_image_url"] = (
        (planned_fabric_batch.image_url if planned_fabric_batch else None)
        or material_preview_image_url(model)
    )
    actuals = _production_order_actuals(db, pid)
    received_by_po = _received_bundle_totals_by_po(db, [pid])
    out["work_orders"] = [
        {
            **row,
            **(
                received_by_po.get(int(row.get("production_order_id") or 0), {})
                if row.get("operation") == "sewing"
                else {}
            ),
        }
        for row in out.get("work_orders") or []
    ]
    out = _project_original_plan_for_detail(db, pid, out, actuals.get("actual_quantity"))
    out.update(actuals)
    return _sign_printing_attachment_urls(out)


@router.post("/production-orders/printing-attachments/upload", status_code=201)
async def upload_production_printing_attachment(
    file: UploadFile = File(...),
    current: User = Depends(require_permissions("planning.production", "printing.records", "*")),
):
    _ = current
    ext = extension_for_upload(file, SAFE_IMAGE_EXTENSIONS | SAFE_DOCUMENT_EXTENSIONS)
    os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
    safe_name = f"po_print_{uuid4().hex}{ext}"
    abs_path = os.path.join(settings.SALES_ORDER_FILES_DIR, safe_name)
    content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
    with open(abs_path, "wb") as f:
        f.write(content)
    file_url = f"/storage/sales-order-files/{safe_name}"
    return {
        "file_url": sign_path(file_url),
        "file_name": file.filename or safe_name,
        "content_type": safe_content_type(ext),
    }


@router.get("/production-orders/{pid}", response_model=ProductionOrderDetail)
def get_po(pid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    return _production_order_detail_payload(db, pid)


@router.patch("/production-orders/{pid}", response_model=ProductionOrderOut)
def update_po(pid: int, payload: dict, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    po = db.get(ProductionOrder, pid)
    if not po: raise HTTPException(404, "Production order not found")
    if _PO_PRE_CUTTING_EDIT_FIELDS.intersection(payload.keys()):
        cutting_wo = (
            db.query(WorkOrder)
            .filter(WorkOrder.production_order_id == pid, WorkOrder.operation == "cutting")
            .order_by(WorkOrder.id.asc())
            .first()
        )
        if cutting_wo and cutting_wo.status not in _PRE_CUTTING_EDIT_STATUSES:
            raise HTTPException(409, "Production order planning fields are locked after cutting starts")
    if "printing_attachments" in payload:
        payload["printing_attachments"] = printing_attachments_for_storage(payload["printing_attachments"])
    for k, v in payload.items():
        if hasattr(po, k):
            setattr(po, k, v)
    log_action(db, current, "update", "ProductionOrder", po.id)
    db.commit(); db.refresh(po)
    return po


@router.put("/production-orders/{pid}/breakdown", response_model=ProductionOrderDetail)
def update_po_breakdown(
    pid: int,
    payload: ProductionOrderBreakdownUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("planning.production", "cutting.records", "packaging.records", "*")),
):
    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")

    actual_qty = int(_production_order_actuals(db, pid).get("actual_quantity") or 0)
    planned_qty = int(po.planned_quantity or 0)
    target_qty = actual_qty if actual_qty > 0 else planned_qty
    if target_qty <= 0:
        raise HTTPException(409, "Order breakdown is editable only after the order quantity is known")

    rows = payload.items or []
    if not rows:
        raise HTTPException(400, "Provide at least one breakdown row")

    existing_rows = db.query(ProductionOrderItem).filter(ProductionOrderItem.production_order_id == pid).all()
    existing_by_id = {int(row.id): row for row in existing_rows}
    normalized: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for idx, row in enumerate(rows, start=1):
        row_id = int(row.id) if row.id else None
        if row_id is not None and row_id not in existing_by_id:
            raise HTTPException(404, f"Breakdown row #{row_id} not found for this production order")

        color = str(row.color or "").strip()
        size = str(row.size or "").strip()
        qty = int(row.planned_quantity or 0)
        if not color or not size:
            raise HTTPException(400, f"Breakdown row {idx}: color and size are required")
        if qty <= 0:
            raise HTTPException(400, f"Breakdown row {idx}: quantity must be greater than zero")

        key = (color.lower(), size.lower())
        if key in seen:
            raise HTTPException(400, f"Duplicate breakdown row for {color} / {size}")
        seen.add(key)
        normalized.append({
            "id": row_id,
            "color": color,
            "size": size,
            "planned_quantity": qty,
            "printing_required": row.printing_required,
        })

    total = sum(row["planned_quantity"] for row in normalized)
    if total != target_qty:
        raise HTTPException(400, f"Breakdown total must equal actual quantity ({target_qty}); got {total}")

    keep_ids: set[int] = set()
    for row in normalized:
        row_id = row["id"]
        if row_id is not None:
            item = existing_by_id[row_id]
            item.color = row["color"]
            item.size = row["size"]
            item.planned_quantity = row["planned_quantity"]
            item.model_id = po.model_id
            if row["printing_required"] is not None:
                item.printing_required = bool(row["printing_required"])
            keep_ids.add(row_id)
        else:
            item = ProductionOrderItem(
                production_order_id=po.id,
                model_id=po.model_id,
                color=row["color"],
                size=row["size"],
                planned_quantity=row["planned_quantity"],
                printing_required=bool(row["printing_required"]),
            )
            db.add(item)

    for row_id, item in existing_by_id.items():
        if row_id not in keep_ids:
            if int(item.completed_quantity or 0) > 0:
                raise HTTPException(409, "Cannot remove breakdown rows with completed quantity")
            db.delete(item)

    log_action(
        db,
        current,
        "update_breakdown",
        "ProductionOrder",
        po.id,
        new_value={"actual_quantity": target_qty, "items": normalized},
    )
    db.commit()
    return _production_order_detail_payload(db, pid)


@router.post("/production-orders/{pid}/create-work-orders")
def create_wos(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("planning.production", "*")),
    include_printing: bool = False,
    cutting_department_code: str = "CUT",
):
    wos = create_work_orders(
        db,
        pid,
        include_printing=include_printing,
        cutting_department_code=cutting_department_code,
    )
    reservation_status = material_reservation_status_for_production_order(db, pid)
    log_action(
        db,
        current,
        "create_work_orders",
        "ProductionOrder",
        pid,
        new_value={
            "count": len(wos),
            "material_reservation_status": reservation_status["plan"].get("status"),
            "material_reservation_complete": reservation_status["plan"].get("is_complete"),
        },
    )
    db.commit()
    return {
        "created": [{"id": w.id, "operation": w.operation} for w in wos],
        "material_reservation": {
            "status": reservation_status["plan"].get("status"),
            "is_complete": reservation_status["plan"].get("is_complete"),
            "warning": reservation_status["plan"].get("warning"),
        },
    }


@router.post("/production-orders/{pid}/reserve-materials", status_code=201)
def reserve_materials_for_production_order(
    pid: int,
    db: DbSession,
    current: User = Depends(require_permissions("planning.reserve_materials", "inventory.reservations.create", "*")),
    payload: ProductionOrderAutoReservationIn | None = Body(default=None),
):
    payload = payload or ProductionOrderAutoReservationIn()
    result = auto_reserve_materials_for_production_order(
        db,
        production_order_id=pid,
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
        pid,
        new_value={
            "mode": payload.mode,
            "created_count": len(reservations),
            "reservation_ids": [int(row.id) for row in reservations],
        },
    )
    db.commit()
    return {
        "production_order_id": pid,
        "created_count": len(reservations),
        "reservations": [_material_reservation_payload(row) for row in reservations],
        "plan": result["plan"],
    }


@router.get("/production-orders/{pid}/material-reservation-status", response_model=MaterialReservationStatusOut)
def get_production_order_material_reservation_status(
    pid: int,
    db: DbSession,
    _: User = Depends(require_permissions("inventory.reservations.view", "planning.reserve_materials", "planning.production", "cutting.records", "*")),
):
    return _material_reservation_status_payload(db, pid)


# Operation order matters for deadline backfill â€” earlier ops finish earlier.
_OP_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
# Default share of total duration consumed by each stage (rough industry mix).
_OP_DURATION_SHARE = {
    "cutting": 0.20, "printing": 0.10, "sewing": 0.45,
    "packaging": 0.15, "storage_transfer": 0.10,
}


@router.post("/production-orders/{pid}/cascade-deadlines")
def cascade_deadlines(pid: int, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    """Distribute the PO deadline backwards across each work order's deadline.

    If the model has a non-zero `sam_minutes`, sewing duration is computed from
    SAM * quantity. Other stages fill the remaining horizon proportionally.
    Otherwise the static 20/10/45/15/10 share is used.
    """
    from app.models import Model as ModelEntity  # local import to avoid cycles

    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")
    if not po.deadline:
        raise HTTPException(400, "Set a Production-Order deadline first")

    end = as_utc(po.deadline)
    start = as_utc(po.start_date) or (end - timedelta(days=30))
    now = datetime.now(timezone.utc)
    # If no explicit start_date is set, avoid generating stage deadlines in the past.
    if po.start_date is None and start < now < end:
        start = now
    if start >= end:
        raise HTTPException(400, "start_date must be before deadline")

    model_obj = db.get(ModelEntity, po.model_id)
    sam = float(model_obj.sam_minutes) if model_obj else 0.0
    qty = _planned_quantity_from_items(db, pid) or int(po.planned_quantity or 0)

    def _per_op_seconds(total_seconds: float, units: int) -> dict[str, float]:
        if sam > 0 and units > 0:
            # Sewing: SAM * qty minutes, capped at 70% of the available horizon.
            sew_seconds = min(total_seconds * 0.7, sam * units * 60.0)
            other_seconds = max(0.0, total_seconds - sew_seconds)
            others = {op: s for op, s in _OP_DURATION_SHARE.items() if op != "sewing"}
            s_sum = sum(others.values()) or 1.0
            out = {op: other_seconds * (s / s_sum) for op, s in others.items()}
            out["sewing"] = sew_seconds
            return out
        return {op: total_seconds * _OP_DURATION_SHARE.get(op, 0.2) for op in _OP_SEQUENCE}

    batches = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.production_order_id == pid)
        .order_by(ProductionBatch.batch_index.asc(), ProductionBatch.id.asc())
        .all()
    )
    batch_map = {b.id: b for b in batches}
    all_wos = db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all()
    groups: dict[int | None, list[WorkOrder]] = {}
    for w in all_wos:
        groups.setdefault(w.production_batch_id, []).append(w)

    updates: list[dict] = []
    for batch_id, wos in groups.items():
        batch = batch_map.get(batch_id) if batch_id is not None else None
        group_end = as_utc(batch.deadline) if batch and batch.deadline else end
        group_start = as_utc(batch.start_date) if batch and batch.start_date else start
        if (batch is None or batch.start_date is None) and po.start_date is None and group_start < now < group_end:
            group_start = now
        if group_start >= group_end:
            group_start = group_end - timedelta(minutes=1)

        group_qty = int(batch.planned_quantity or 0) if batch else max(0, qty)
        total_seconds = max(60.0, (group_end - group_start).total_seconds())
        per_op = _per_op_seconds(total_seconds, group_qty)
        by_op = {w.operation: w for w in wos}

        cursor = group_start
        for op in _OP_SEQUENCE:
            wo = by_op.get(op)
            if not wo:
                continue
            cursor = cursor + timedelta(seconds=per_op.get(op, 0))
            deadline = min(cursor, group_end)
            wo.deadline = deadline
            updates.append({
                "work_order_id": wo.id,
                "operation": op,
                "batch_id": batch_id,
                "deadline": deadline.isoformat(),
            })

    log_action(
        db,
        current,
        "cascade_deadlines",
        "ProductionOrder",
        pid,
        new_value={"updates": updates, "sam_minutes": sam, "qty": qty},
    )
    db.commit()
    return {"updates": updates, "sam_minutes": sam}


@router.post("/production-orders/{pid}/admin-repair-totals")
def admin_repair_totals(pid: int, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    """Admin recovery tool:
    Rebuild WO counters from source records while preserving the original plan.
    Useful when duplicate submissions inflated stage totals.
    """
    if not is_admin(current):
        raise HTTPException(403, "Admin only action")

    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")

    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == pid).all()
    by_op = {w.operation: w for w in work_orders}
    now = datetime.now(timezone.utc)
    planned_from_items = _planned_quantity_from_items(db, pid)

    def _clamp_pass(planned: int, value: int) -> int:
        return max(0, int(value or 0))

    def _set_wo(wo: WorkOrder, *, input_qty: int, output_qty: int, passed_qty: int, failed_qty: int, rework_qty: int | None = None):
        before = {
            "actual_input_qty": int(wo.actual_input_qty or 0),
            "actual_output_qty": int(wo.actual_output_qty or 0),
            "passed_qty": int(wo.passed_qty or 0),
            "failed_qty": int(wo.failed_qty or 0),
            "rework_qty": int(wo.rework_qty or 0),
            "status": wo.status,
        }
        wo.actual_input_qty = max(0, int(input_qty or 0))
        wo.actual_output_qty = max(0, int(output_qty or 0))
        wo.passed_qty = max(0, int(passed_qty or 0))
        wo.failed_qty = max(0, int(failed_qty or 0))
        if rework_qty is not None:
            wo.rework_qty = max(0, int(rework_qty or 0))

        if wo.status not in ("cancelled", "rejected"):
            planned = max(0, int(wo.planned_output_qty or 0))
            processed = processed_work_order_qty(db, wo)
            if planned > 0 and processed >= planned:
                if wo.status != "completed":
                    wo.status = "completed"
                if not wo.end_time:
                    wo.end_time = now
            elif processed > 0 and wo.status in ("waiting", "pending", "collected", "new", "planning"):
                wo.status = "in_progress"
                if not wo.start_time:
                    wo.start_time = now

        after = {
            "actual_input_qty": int(wo.actual_input_qty or 0),
            "actual_output_qty": int(wo.actual_output_qty or 0),
            "passed_qty": int(wo.passed_qty or 0),
            "failed_qty": int(wo.failed_qty or 0),
            "rework_qty": int(wo.rework_qty or 0),
            "status": wo.status,
        }
        return before, after

    changes: list[dict] = []

    if planned_from_items > 0 and int(po.planned_quantity or 0) > planned_from_items:
        before = int(po.planned_quantity or 0)
        po.planned_quantity = planned_from_items
        changes.append({
            "production_order_id": pid,
            "field": "planned_quantity",
            "before": before,
            "after": planned_from_items,
        })
        for row in work_orders:
            before_row = {
                "planned_input_qty": int(row.planned_input_qty or 0),
                "planned_output_qty": int(row.planned_output_qty or 0),
            }
            if int(row.planned_output_qty or 0) > planned_from_items:
                row.planned_output_qty = planned_from_items
            if row.operation != "cutting" and int(row.planned_input_qty or 0) > planned_from_items:
                row.planned_input_qty = planned_from_items
            after_row = {
                "planned_input_qty": int(row.planned_input_qty or 0),
                "planned_output_qty": int(row.planned_output_qty or 0),
            }
            if before_row != after_row:
                changes.append({
                    "work_order_id": row.id,
                    "operation": row.operation,
                    "before": before_row,
                    "after": after_row,
                })

    cut_wo = by_op.get("cutting")
    if cut_wo:
        cut_input, cut_passed, cut_failed = db.query(
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        ).filter(CuttingRecord.work_order_id == cut_wo.id).one()
        passed = max(0, int(cut_passed or 0))
        output = passed
        before, after = _set_wo(
            cut_wo,
            input_qty=max(int(cut_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(cut_failed or 0),
            rework_qty=int(cut_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": cut_wo.id, "operation": "cutting", "before": before, "after": after})
        propagate_cutting_plan_from_output(db, cut_wo)

    prt_wo = by_op.get("printing")
    if prt_wo:
        prt_input, prt_passed, prt_failed = db.query(
            func.coalesce(func.sum(PrintingRecord.input_qty), 0),
            func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
        ).filter(PrintingRecord.work_order_id == prt_wo.id).one()
        planned = int(prt_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(prt_passed or 0))
        output = passed
        before, after = _set_wo(
            prt_wo,
            input_qty=max(int(prt_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(prt_failed or 0),
            rework_qty=int(prt_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": prt_wo.id, "operation": "printing", "before": before, "after": after})

    sew_wo = by_op.get("sewing")
    if sew_wo:
        sew_input, sew_passed, sew_failed, sew_rework = db.query(
            func.coalesce(func.sum(SewingRecord.input_qty), 0),
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
            func.coalesce(func.sum(SewingRecord.failed_qty), 0),
            func.coalesce(func.sum(SewingRecord.rework_qty), 0),
        ).filter(SewingRecord.work_order_id == sew_wo.id).one()
        planned = int(sew_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(sew_passed or 0))
        output = passed
        before, after = _set_wo(
            sew_wo,
            input_qty=max(int(sew_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(sew_failed or 0),
            rework_qty=int(sew_rework or 0),
        )
        if before != after:
            changes.append({"work_order_id": sew_wo.id, "operation": "sewing", "before": before, "after": after})

    pkg_wo = by_op.get("packaging")
    if pkg_wo:
        pkg_input, rec_packed, pkg_failed = db.query(
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
            func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
        ).filter(PackagingRecord.work_order_id == pkg_wo.id).one()

        packages_packed = db.query(func.coalesce(func.sum(Package.total_quantity), 0)).filter(
            Package.production_order_id == pid,
            Package.status.in_(["packed", "received_in_storage", "reserved", "shipped", "delivered"]),
        ).scalar() or 0

        source_packed = int(packages_packed or 0) if int(packages_packed or 0) > 0 else int(rec_packed or 0)
        planned = int(pkg_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, source_packed)
        output = passed
        before, after = _set_wo(
            pkg_wo,
            input_qty=max(int(pkg_input or 0), passed),
            output_qty=output,
            passed_qty=passed,
            failed_qty=int(pkg_failed or 0),
            rework_qty=int(pkg_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({
                "work_order_id": pkg_wo.id,
                "operation": "packaging",
                "source": "packages" if int(packages_packed or 0) > 0 else "packaging_records",
                "before": before,
                "after": after,
            })

    stg_wo = by_op.get("storage_transfer")
    if stg_wo:
        received_total = _storage_received_total(db, pid)
        planned = int(stg_wo.planned_output_qty or 0)
        passed = _clamp_pass(planned, int(received_total or 0))
        output = passed
        before, after = _set_wo(
            stg_wo,
            input_qty=passed,
            output_qty=output,
            passed_qty=passed,
            failed_qty=0,
            rework_qty=int(stg_wo.rework_qty or 0),
        )
        if before != after:
            changes.append({"work_order_id": stg_wo.id, "operation": "storage_transfer", "before": before, "after": after})

    sync_production_order_status(db, pid)
    log_action(db, current, "admin_repair_totals", "ProductionOrder", pid, new_value={"changes": changes})
    db.commit()

    return {"production_order_id": pid, "changed_count": len(changes), "changes": changes}


# ===== Work Orders =====
@router.get("/work-orders", response_model=list[WorkOrderOut])
def list_wos(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    department_id: int | None = None,
    status: str | None = None,
    production_order_id: int | None = None,
    operation: str | None = None,
    only_active: bool = False,
    unassigned_flow: bool = False,
    only_received_sewing: bool = False,
):
    qry = db.query(WorkOrder).options(joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order))
    if department_id: qry = qry.filter(WorkOrder.department_id == department_id)
    if status: qry = qry.filter(WorkOrder.status == status)
    if production_order_id: qry = qry.filter(WorkOrder.production_order_id == production_order_id)
    if operation: qry = qry.filter(WorkOrder.operation == operation)
    if only_active: qry = qry.filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
    if unassigned_flow:
        if not operation:
            qry = qry.filter(WorkOrder.operation == "sewing")
        qry = qry.filter(WorkOrder.sewing_flow_id.is_(None))
    if only_received_sewing:
        qry = qry.filter(WorkOrder.operation == "sewing")
        received_po_ids = (
            db.query(Bundle.production_order_id)
            .filter(Bundle.status == "received_sewing")
            .distinct()
        )
        qry = qry.filter(WorkOrder.production_order_id.in_(received_po_ids))
    rows = qry.order_by(WorkOrder.id.desc()).all()
    po_ids = [int(w.production_order_id) for w in rows]
    images_by_po = _work_order_images_by_po(db, po_ids)
    if only_received_sewing:
        return _received_sewing_work_order_payloads(db, rows, images_by_po)
    received_by_po = _received_bundle_totals_by_po(db, [int(w.production_order_id) for w in rows if w.operation == "sewing"])
    return [_work_order_payload(w, received_by_po, images_by_po) for w in rows]


@router.get("/work-orders/{wid}", response_model=WorkOrderOut)
def get_wo(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order))
        .filter(WorkOrder.id == wid)
        .first()
    )
    if not wo: raise HTTPException(404, "Work order not found")
    received_by_po = _received_bundle_totals_by_po(db, [int(wo.production_order_id)]) if wo.operation == "sewing" else {}
    images_by_po = _work_order_images_by_po(db, [int(wo.production_order_id)])
    return _work_order_payload(wo, received_by_po, images_by_po)


@router.get("/work-orders/{wid}/replacement-status")
def work_order_replacement_status(
    wid: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    return _replacement_status_payload(db, wo)


@router.patch("/work-orders/{wid}", response_model=WorkOrderOut)
def update_wo(wid: int, payload: WorkOrderUpdate, db: DbSession, current: User = Depends(require_permissions(*_PRODUCTION_FLOOR_PERMS))):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("status") == "completed":
        _ensure_replacements_do_not_block_completion(db, wo)
    if (
        wo.operation == "storage_transfer"
        and changes.get("status") in ("in_progress", "pending", "collected", "ready", "paused")
        and _storage_received_total(db, int(wo.production_order_id)) <= 0
    ):
        raise HTTPException(400, "Storage transfer starts only when packages are received into storage.")

    if wo.operation == "sewing" and "sewing_flow_id" in changes and changes["sewing_flow_id"]:
        target_flow = db.get(SewingFlow, int(changes["sewing_flow_id"]))
        if not target_flow:
            raise HTTPException(404, "Sewing flow not found")
        if not target_flow.is_active:
            raise HTTPException(400, "Sewing flow is inactive")
        now = datetime.now(timezone.utc)
        committed = _flow_committed_today(db, target_flow.id, now)
        own_remaining = max(0, int(wo.planned_output_qty or 0) - int(wo.passed_qty or 0))
        if wo.sewing_flow_id == target_flow.id:
            has_split = db.query(SewingAssignment.id).filter(
                SewingAssignment.work_order_id == wo.id,
                SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
            ).first()
            if not has_split:
                committed = max(0, committed - own_remaining)
        projected = committed + own_remaining
        if int(target_flow.capacity_per_day or 0) > 0 and projected > int(target_flow.capacity_per_day):
            raise HTTPException(
                409,
                f"Capacity full: {target_flow.code} daily load would be {projected} vs capacity {target_flow.capacity_per_day}",
            )

    previous_assignee = wo.assigned_to
    for k, v in changes.items():
        setattr(wo, k, v)
    # If assignment changed, notify the new assignee so they know they have a new job.
    if "assigned_to" in changes and wo.assigned_to and wo.assigned_to != previous_assignee:
        from app.services.notifications import notify
        notify(
            db, user_id=wo.assigned_to,
            title=f"New job: {wo.operation} work order #{wo.id}",
            message=f"You were assigned to work order #{wo.id} ({wo.operation}, status: {wo.status}).",
            link=f"/work-orders/{wo.id}/{wo.operation}",
        )
    log_action(db, current, "update", "WorkOrder", wo.id, new_value=changes)
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/start", response_model=WorkOrderOut)
def start_wo(wid: int, db: DbSession, current: User = Depends(require_permissions(*_PRODUCTION_FLOOR_PERMS))):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation == "storage_transfer":
        raise HTTPException(400, "Storage transfer starts automatically when packages are received into storage.")
    upstream = _upstream_work_order_for_start(db, wo)
    if upstream:
        upstream_output = max(int(upstream.actual_output_qty or 0), int(upstream.passed_qty or 0))
        if upstream_output <= 0:
            log_action(
                db,
                current,
                "block_start_missing_upstream_output",
                "WorkOrder",
                wo.id,
                new_value={
                    "production_order_id": wo.production_order_id,
                    "operation": wo.operation,
                    "upstream_work_order_id": upstream.id,
                    "upstream_operation": upstream.operation,
                    "upstream_status": upstream.status,
                    "upstream_output": upstream_output,
                },
            )
            db.commit()
            raise HTTPException(
                409,
                f"{wo.operation.replace('_', ' ').title()} cannot start until "
                f"{upstream.operation.replace('_', ' ')} has passed output.",
            )
    if wo.operation == "cutting" and missing_material_reservation_for_cutting(db, int(wo.production_order_id)):
        status = material_reservation_status_for_production_order(db, int(wo.production_order_id))
        log_action(
            db,
            current,
            "block_start_missing_material_reservation",
            "WorkOrder",
            wo.id,
            new_value={
                "production_order_id": wo.production_order_id,
                "reservation_status": status["plan"].get("status"),
                "remaining_to_reserve": status["summary"].get("remaining_to_reserve"),
                "setting": "require_material_reservation_before_cutting",
            },
        )
        db.commit()
        raise HTTPException(400, "Material reservation is incomplete. Reserve required materials before starting cutting.")
    if wo.operation == "sewing":
        ensure_accessories_issued_for_sewing(db, int(wo.production_order_id))
    wo.status = "in_progress"
    wo.start_time = datetime.now(timezone.utc)
    reservation_status = None
    if wo.operation == "cutting":
        reservation_status = material_reservation_status_for_production_order(db, int(wo.production_order_id))["plan"]
    log_action(
        db,
        current,
        "start",
        "WorkOrder",
        wo.id,
        new_value={
            "material_reservation_status": reservation_status.get("status") if reservation_status else None,
            "material_reservation_complete": reservation_status.get("is_complete") if reservation_status else None,
        } if reservation_status else None,
    )
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/collect", response_model=WorkOrderOut)
def collect_printing_wo(
    wid: int,
    payload: PrintingCollectIn,
    db: DbSession,
    current: User = Depends(require_permissions("printing.records", "planning.production", "*")),
):
    """Master intake for printing queue: confirm collection and set print ETA."""
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "printing":
        raise HTTPException(400, "Collect action is only allowed for printing work orders")
    if wo.status in ("in_progress", "completed", "rejected", "cancelled"):
        raise HTTPException(409, f"Cannot collect work order in status '{wo.status}'")

    wo.status = "collected"
    wo.deadline = payload.deadline
    if payload.notes is not None:
        wo.notes = payload.notes

    log_action(
        db,
        current,
        "collect",
        "WorkOrder",
        wo.id,
        new_value={
            "status": wo.status,
            "deadline": wo.deadline,
            "notes": wo.notes,
        },
    )
    db.commit()
    db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/complete", response_model=WorkOrderOut)
def complete_wo(wid: int, db: DbSession, current: User = Depends(require_permissions(*_PRODUCTION_FLOOR_PERMS))):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    _ensure_replacements_do_not_block_completion(db, wo)
    wo.status = "completed"
    wo.end_time = datetime.now(timezone.utc)
    log_action(db, current, "complete", "WorkOrder", wo.id)
    db.commit(); db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/complete-cutting-shortage", response_model=WorkOrderOut)
def complete_cutting_with_shortage(
    wid: int,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "planning.production", "*")),
):
    """Close cutting below plan and carry only its usable output forward.

    The original production plan stays unchanged. The missing quantity is
    recorded on the cutting work order as failed output, which lets downstream
    stages finish against the smaller quantity without pretending extra pieces
    were produced.
    """
    wo = (
        db.query(WorkOrder)
        .filter(WorkOrder.id == wid)
        .with_for_update()
        .first()
    )
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "This action is only available for cutting work orders")
    if wo.status in ("completed", "rejected", "cancelled"):
        raise HTTPException(409, f"Cannot complete cutting in status '{wo.status}'")

    cut_sum, passed_sum, defective_sum = (
        db.query(
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        )
        .filter(CuttingRecord.work_order_id == wo.id)
        .one()
    )
    planned = max(0, int(wo.planned_output_qty or 0))
    passed = max(0, int(passed_sum or 0))
    defective = max(0, int(defective_sum or 0))
    if planned <= 0:
        raise HTTPException(409, "Cutting has no planned quantity")
    if passed <= 0:
        raise HTTPException(409, "Record at least one usable cut piece before completing cutting")
    if passed + defective >= planned:
        raise HTTPException(409, "Cutting already has enough recorded output to complete normally")

    shortage = planned - passed - defective
    before = {
        "status": wo.status,
        "planned_output_qty": planned,
        "actual_input_qty": int(wo.actual_input_qty or 0),
        "actual_output_qty": int(wo.actual_output_qty or 0),
        "passed_qty": int(wo.passed_qty or 0),
        "failed_qty": int(wo.failed_qty or 0),
    }
    now = datetime.now(timezone.utc)
    wo.actual_input_qty = max(int(cut_sum or 0), passed + defective)
    wo.actual_output_qty = passed
    wo.passed_qty = passed
    # Failed output includes recorded defects plus the explicitly accepted
    # uncut shortage, so downstream completion math still reconciles to plan.
    wo.failed_qty = defective + shortage
    wo.status = "completed"
    wo.start_time = wo.start_time or now
    wo.end_time = now

    has_printing_stage = _context_work_order(db, wo, "printing") is not None
    sewing_stage = _context_work_order(db, wo, "sewing")
    accessory_plan = None
    allow_next_stage_start = True
    if not has_printing_stage and sewing_stage is not None:
        accessory_plan = sync_sewing_accessory_block(db, int(wo.production_order_id))
        allow_next_stage_start = bool(accessory_plan.get("is_complete")) if accessory_plan else True

    advance_workflow(
        db,
        wo,
        trigger_output_qty=passed,
        allow_next_stage_start=allow_next_stage_start,
    )
    if not allow_next_stage_start and accessory_plan:
        _notify_accessory_issue_block(db, wo, accessory_plan, "cutting shortage completion")

    log_action(
        db,
        current,
        "complete_cutting_with_shortage",
        "WorkOrder",
        wo.id,
        old_value=before,
        new_value={
            "status": wo.status,
            "planned_output_qty": planned,
            "actual_input_qty": int(wo.actual_input_qty or 0),
            "actual_output_qty": int(wo.actual_output_qty or 0),
            "passed_qty": int(wo.passed_qty or 0),
            "failed_qty": int(wo.failed_qty or 0),
            "recorded_defective_qty": defective,
            "accepted_shortage_qty": shortage,
            "next_stage_started": allow_next_stage_start,
        },
    )
    db.commit()
    db.refresh(wo)
    return wo


@router.post("/work-orders/{wid}/split-batches")
def split_cutting_work_order_batches(
    wid: int,
    payload: SplitWorkOrderBatchesIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "planning.production", "*")),
):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Only cutting work orders can be split into batches")
    if wo.production_batch_id is not None:
        raise HTTPException(409, "This work order is already assigned to a batch")

    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    existing_batches = db.query(ProductionBatch.id).filter(ProductionBatch.production_order_id == po.id).first()
    if existing_batches:
        raise HTTPException(409, "Production order already has batches")

    rows = payload.batches or []
    if not rows:
        raise HTTPException(400, "Provide at least one batch")
    if any(int(row.planned_quantity or 0) <= 0 for row in rows):
        raise HTTPException(400, "Each batch quantity must be greater than zero")
    total = sum(int(row.planned_quantity or 0) for row in rows)

    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()
    work_order_ids = [w.id for w in work_orders]
    if not work_order_ids:
        raise HTTPException(400, "No work orders found for this production order")

    has_activity = (
        db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(PrintingRecord.id).filter(PrintingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(SewingRecord.id).filter(SewingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(PackagingRecord.id).filter(PackagingRecord.work_order_id.in_(work_order_ids)).first()
        or db.query(SewingAssignment.id).filter(SewingAssignment.work_order_id.in_(work_order_ids)).first()
        or db.query(QualityCheck.id).filter(QualityCheck.work_order_id.in_(work_order_ids)).first()
        or db.query(WasteRecord.id).filter(WasteRecord.work_order_id.in_(work_order_ids)).first()
    )
    if has_activity:
        raise HTTPException(409, "Cannot split: this order already has production activity records")

    batch_payload = [row.model_dump() for row in rows]
    created_batches = create_production_batches(db, po.id, batch_payload)

    log_action(
        db,
        current,
        "split_into_batches",
        "ProductionOrder",
        po.id,
        new_value={
            "batch_count": len(created_batches),
            "total_quantity": total,
            "work_order_id": wo.id,
            "kept_single_work_order": True,
        },
    )
    db.commit()
    return {
        "production_order_id": po.id,
        "batch_count": len(created_batches),
        "work_order_id": wo.id,
        "kept_single_work_order": True,
    }


@router.post("/work-orders/{wid}/extra-batch")
def add_extra_cutting_batch(
    wid: int,
    payload: ExtraCuttingBatchIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "planning.production", "*")),
):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Only cutting work orders can add cutting batches")
    if wo.production_batch_id is not None:
        raise HTTPException(409, "This work order is already assigned to a batch")

    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    qty = int(payload.planned_quantity or 0)
    if qty <= 0:
        raise HTTPException(400, "Batch quantity must be greater than zero")

    max_index = int(
        db.query(func.coalesce(func.max(ProductionBatch.batch_index), 0))
        .filter(ProductionBatch.production_order_id == po.id)
        .scalar()
        or 0
    )
    batch_index = max_index + 1
    proposed_no = f"{int(po.id):04d}-{batch_index:02d}"
    batch_no = proposed_no
    suffix = 2
    while db.query(ProductionBatch.id).filter(
        ProductionBatch.production_order_id == po.id,
        ProductionBatch.batch_no == batch_no,
    ).first():
        batch_no = f"{proposed_no}-{suffix}"
        suffix += 1

    batch = ProductionBatch(
        production_order_id=po.id,
        batch_no=batch_no,
        batch_index=batch_index,
        name=(str(payload.name or "").strip() or f"Extra batch {batch_index}"),
        planned_quantity=qty,
        start_date=payload.start_date,
        deadline=payload.deadline,
        notes=(str(payload.notes or "").strip() or None),
    )
    db.add(batch)
    db.flush()

    log_action(
        db,
        current,
        "add_extra_cutting_batch",
        "ProductionBatch",
        batch.id,
        new_value={
            "production_order_id": po.id,
            "work_order_id": wo.id,
            "batch_no": batch.batch_no,
            "planned_quantity": qty,
        },
    )
    db.commit()
    db.refresh(batch)
    return {
        "id": batch.id,
        "production_order_id": batch.production_order_id,
        "batch_no": batch.batch_no,
        "batch_index": batch.batch_index,
        "name": batch.name,
        "planned_quantity": batch.planned_quantity,
        "start_date": batch.start_date,
        "deadline": batch.deadline,
        "notes": batch.notes,
    }


@router.get("/work-orders/{wid}/cutting-batch-progress")
def cutting_batch_progress(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Work order is not a cutting operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            CuttingRecord.production_batch_id,
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        )
        .filter(CuttingRecord.work_order_id == wo.id)
        .group_by(CuttingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, cut_sum, passed_sum, defective_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "cut_pieces": int(cut_sum or 0),
            "passed_pieces": int(passed_sum or 0),
            "defective_pieces": int(defective_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_pieces", 0))
        defective = int(totals.get("defective_pieces", 0))
        processed = passed + defective
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "cut_pieces": int(totals.get("cut_pieces", 0)),
            "passed_pieces": passed,
            "defective_pieces": defective,
            "remaining_quantity": max(0, planned - processed),
            "progress_pct": round((100.0 * processed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/printing-batch-progress")
def printing_batch_progress(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "printing":
        raise HTTPException(400, "Work order is not a printing operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            PrintingRecord.production_batch_id,
            func.coalesce(func.sum(PrintingRecord.input_qty), 0),
            func.coalesce(func.sum(PrintingRecord.printed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.passed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.rejected_qty), 0),
        )
        .filter(PrintingRecord.work_order_id == wo.id)
        .group_by(PrintingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, printed_sum, passed_sum, rejected_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "printed_qty": int(printed_sum or 0),
            "passed_qty": int(passed_sum or 0),
            "rejected_qty": int(rejected_sum or 0),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_qty", 0))
        rejected = int(totals.get("rejected_qty", 0))
        processed = passed + rejected
        planned = int(b.planned_quantity or 0)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "printed_qty": int(totals.get("printed_qty", 0)),
            "passed_qty": passed,
            "rejected_qty": rejected,
            "remaining_quantity": max(0, planned - processed),
            "progress_pct": round((100.0 * processed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/sewing-batch-progress")
def sewing_batch_progress(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing":
        raise HTTPException(400, "Work order is not a sewing operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            SewingRecord.production_batch_id,
            func.coalesce(func.sum(SewingRecord.input_qty), 0),
            func.coalesce(func.sum(SewingRecord.sewn_qty), 0),
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
            func.coalesce(func.sum(SewingRecord.failed_qty), 0),
            func.coalesce(func.sum(SewingRecord.rework_qty), 0),
            func.coalesce(func.sum(SewingRecord.rejected_qty), 0),
        )
        .filter(SewingRecord.work_order_id == wo.id)
        .group_by(SewingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, sewn_sum, passed_sum, failed_sum, rework_sum, rejected_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "sewn_qty": int(sewn_sum or 0),
            "passed_qty": int(passed_sum or 0),
            "failed_qty": int(failed_sum or 0),
            "rework_qty": int(rework_sum or 0),
            "rejected_qty": int(rejected_sum or 0),
        }

    replacement_by_batch: dict[int, dict[str, int]] = {}
    replacement_rows = (
        db.query(
            SewingReplacementRequest.production_batch_id,
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.cut_qty), 0),
            func.coalesce(func.sum(SewingReplacementRequest.cut_qty - SewingReplacementRequest.replaced_qty), 0),
            func.coalesce(func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.replaced_qty), 0),
        )
        .filter(SewingReplacementRequest.sewing_work_order_id == wo.id)
        .group_by(SewingReplacementRequest.production_batch_id)
        .all()
    )
    for batch_id, waiting_cutting, waiting_sewing, open_qty in replacement_rows:
        if batch_id is None:
            continue
        replacement_by_batch[int(batch_id)] = {
            "waiting_cutting_qty": max(0, int(waiting_cutting or 0)),
            "waiting_sewing_qty": max(0, int(waiting_sewing or 0)),
            "waiting_replacement_qty": max(0, int(open_qty or 0)),
        }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_qty", 0))
        failed = int(totals.get("failed_qty", 0))
        rejected = int(totals.get("rejected_qty", 0))
        processed = passed
        planned = int(b.planned_quantity or 0)
        replacement = replacement_by_batch.get(int(b.id), {})
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "sewn_qty": int(totals.get("sewn_qty", 0)),
            "passed_qty": passed,
            "failed_qty": failed,
            "rework_qty": int(totals.get("rework_qty", 0)),
            "rejected_qty": rejected,
            "waiting_cutting_qty": int(replacement.get("waiting_cutting_qty", 0)),
            "waiting_sewing_qty": int(replacement.get("waiting_sewing_qty", 0)),
            "waiting_replacement_qty": int(replacement.get("waiting_replacement_qty", 0)),
            "remaining_quantity": max(0, planned - processed),
            "progress_pct": round((100.0 * processed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


@router.get("/work-orders/{wid}/packaging-batch-progress")
def packaging_batch_progress(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "packaging":
        raise HTTPException(400, "Work order is not a packaging operation")

    _, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            PackagingRecord.production_batch_id,
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0),
            func.coalesce(func.sum(PackagingRecord.damaged_qty), 0),
        )
        .filter(PackagingRecord.work_order_id == wo.id)
        .group_by(PackagingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, input_sum, packed_sum, damaged_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "input_qty": int(input_sum or 0),
            "packed_qty": int(packed_sum or 0),
            "damaged_qty": int(damaged_sum or 0),
        }

    batch_ids = {int(b.id) for b in batches}
    packaged_by_batch: dict[int, int] = {}
    allocated_package_ids: set[int] = set()
    allocation_rows = (
        db.query(
            PackageBatchAllocation.package_id,
            PackageBatchAllocation.production_batch_id,
            func.coalesce(func.sum(PackageBatchAllocation.quantity), 0),
        )
        .join(Package, Package.id == PackageBatchAllocation.package_id)
        .filter(
            Package.production_order_id == wo.production_order_id,
            PackageBatchAllocation.production_batch_id.in_(batch_ids),
        )
        .group_by(PackageBatchAllocation.package_id, PackageBatchAllocation.production_batch_id)
        .all()
    )
    for package_id, batch_id, quantity in allocation_rows:
        allocated_package_ids.add(int(package_id))
        packaged_by_batch[int(batch_id)] = packaged_by_batch.get(int(batch_id), 0) + int(quantity or 0)

    fallback_qry = db.query(
        Package.production_batch_id,
        func.coalesce(func.sum(Package.total_quantity), 0),
    ).filter(
        Package.production_order_id == wo.production_order_id,
        Package.production_batch_id.in_(batch_ids),
    )
    if allocated_package_ids:
        fallback_qry = fallback_qry.filter(~Package.id.in_(allocated_package_ids))
    for batch_id, quantity in fallback_qry.group_by(Package.production_batch_id).all():
        if batch_id is None:
            continue
        packaged_by_batch[int(batch_id)] = packaged_by_batch.get(int(batch_id), 0) + int(quantity or 0)

    waiting_replacement_by_batch: dict[int, int] = {}
    sew_wo = _context_work_order(db, wo, "sewing")
    if sew_wo:
        replacement_rows = (
            db.query(
                SewingReplacementRequest.production_batch_id,
                func.coalesce(
                    func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.replaced_qty),
                    0,
                ),
            )
            .filter(SewingReplacementRequest.sewing_work_order_id == sew_wo.id)
            .group_by(SewingReplacementRequest.production_batch_id)
            .all()
        )
        for batch_id, open_qty in replacement_rows:
            if batch_id is None:
                continue
            waiting_replacement_by_batch[int(batch_id)] = max(0, int(open_qty or 0))

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        packed = int(totals.get("packed_qty", 0))
        damaged = int(totals.get("damaged_qty", 0))
        waiting_replacement = int(waiting_replacement_by_batch.get(int(b.id), 0))
        packaged = int(packaged_by_batch.get(int(b.id), 0))
        planned = int(b.planned_quantity or 0)
        processed = min(planned, packed + damaged)
        items.append({
            "id": b.id,
            "batch_no": b.batch_no,
            "batch_index": b.batch_index,
            "name": b.name,
            "planned_quantity": planned,
            "input_qty": int(totals.get("input_qty", 0)),
            "packed_qty": packed,
            "packaged_qty": packaged,
            "available_to_package": max(0, packed - packaged),
            "damaged_qty": damaged,
            "waiting_replacement_qty": waiting_replacement,
            "remaining_quantity": max(0, planned - processed),
            "progress_pct": round((100.0 * processed / planned), 1) if planned > 0 else 0.0,
            "start_date": b.start_date,
            "deadline": b.deadline,
            "notes": b.notes,
        })
    return {"work_order_id": wo.id, "items": items}


# ===== Cutting =====
_MAX_BUNDLES_PER_CUTTING_RECORD = 1000


def _replacement_cut_total(db: DbSession, cutting_work_order_id: int) -> int:
    return int(
        db.query(func.coalesce(func.sum(SewingReplacementRequest.cut_qty), 0))
        .filter(SewingReplacementRequest.cutting_work_order_id == cutting_work_order_id)
        .scalar()
        or 0
    )


def _allocate_replacement_cut(
    db: DbSession,
    wo: WorkOrder,
    production_batch_id: int | None,
    quantity: int,
) -> int:
    remaining = max(0, int(quantity or 0))
    if remaining <= 0:
        return 0
    qry = db.query(SewingReplacementRequest).filter(
        SewingReplacementRequest.cutting_work_order_id == wo.id,
        SewingReplacementRequest.cut_qty < SewingReplacementRequest.requested_qty,
    )
    if production_batch_id is None:
        qry = qry.filter(SewingReplacementRequest.production_batch_id.is_(None))
    else:
        qry = qry.filter(SewingReplacementRequest.production_batch_id == production_batch_id)
    allocated = 0
    for request in qry.order_by(SewingReplacementRequest.id).all():
        needed = max(0, int(request.requested_qty or 0) - int(request.cut_qty or 0))
        take = min(needed, remaining)
        if take <= 0:
            continue
        request.cut_qty = int(request.cut_qty or 0) + take
        request.status = "waiting_sewing" if request.cut_qty >= request.requested_qty else "waiting_cutting"
        remaining -= take
        allocated += take
        if remaining <= 0:
            break
    return allocated


def _parse_cutting_bundle_specs(specs: list[dict]) -> list[dict]:
    parsed: list[dict] = []
    total = 0
    for i, spec in enumerate(specs or [], start=1):
        try:
            count = int(spec.get("count", 1))
            qty = int(spec.get("quantity", 0))
        except (TypeError, ValueError):
            raise HTTPException(400, f"Bundle plan row {i}: 'count' and 'quantity' must be whole numbers")
        if count < 0 or qty < 0:
            raise HTTPException(400, f"Bundle plan row {i}: 'count' and 'quantity' cannot be negative")
        if count == 0:
            continue
        color = str(spec.get("color") or "").strip()
        size = str(spec.get("size") or "").strip()
        if not color or not size:
            raise HTTPException(400, f"Bundle plan row {i}: 'color' and 'size' are required")
        total += count
        if total > _MAX_BUNDLES_PER_CUTTING_RECORD:
            raise HTTPException(400, f"Bundle plan would create more than {_MAX_BUNDLES_PER_CUTTING_RECORD} bundles")
        raw_next = str(spec.get("next") or "").strip().lower()
        raw_factory = spec.get("sewing_factory") or spec.get("sewingFactory") or spec.get("factory")
        if not raw_factory and is_sewing_department_code(raw_next):
            raw_factory = raw_next
        factory_code = resolve_sewing_factory_code(str(raw_factory) if raw_factory else None)
        parsed.append({
            "count": count,
            "quantity": qty,
            "color": color,
            "size": size,
            "factory_code": factory_code,
            "next_code": "PRT" if raw_next == "printing" else factory_code,
        })
    return parsed


@router.post("/cutting/records", status_code=201)
def post_cutting(payload: CuttingRecordIn, db: DbSession, current: User = Depends(require_permissions("cutting.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting": raise HTTPException(400, "Work order is not a cutting operation")
    _gate_record_submission(wo)
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="cutting",
    )

    bundle_specs = _parse_cutting_bundle_specs(payload.bundles or [])
    requested_passed_pieces = max(0, int(payload.passed_pieces or 0))
    defective_pieces = max(0, int(payload.defective_pieces or 0))
    requested_cut_pieces = max(0, int(payload.cut_pieces or 0))
    bundle_total = sum(b["quantity"] * b["count"] for b in bundle_specs)
    if bundle_specs:
        passed_pieces = bundle_total
        cut_pieces = max(requested_cut_pieces, passed_pieces + defective_pieces)
    else:
        passed_pieces = requested_passed_pieces
        cut_pieces = requested_cut_pieces
    if passed_pieces + defective_pieces > cut_pieces:
        raise HTTPException(400, "Passed and defective pieces cannot exceed cut pieces")

    if batch_id is not None:
        batch = db.get(ProductionBatch, batch_id)
        passed_before, defective_before = db.query(
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        ).filter(
            CuttingRecord.work_order_id == wo.id,
            CuttingRecord.production_batch_id == batch_id,
        ).one()
        replacement_cut_before = int(
            db.query(func.coalesce(func.sum(SewingReplacementRequest.cut_qty), 0))
            .filter(
                SewingReplacementRequest.cutting_work_order_id == wo.id,
                SewingReplacementRequest.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        original_passed_before = max(0, int(passed_before or 0) - replacement_cut_before)
        original_processed_before = original_passed_before + max(0, int(defective_before or 0))
        original_plan = int(batch.planned_quantity or 0) if batch else 0
    else:
        replacement_cut_before = _replacement_cut_total(db, wo.id)
        original_passed_before = max(0, int(wo.passed_qty or 0) - replacement_cut_before)
        original_processed_before = original_passed_before + max(0, int(wo.failed_qty or 0))
        original_plan = int(wo.planned_output_qty or 0)
    original_remaining_before = max(0, original_plan - original_processed_before)

    rec = CuttingRecord(
        work_order_id=payload.work_order_id,
        production_batch_id=batch_id,
        fabric_batch_id=payload.fabric_batch_id,
        input_quantity=payload.input_quantity,
        input_unit=payload.input_unit,
        cut_pieces=cut_pieces,
        passed_pieces=passed_pieces,
        defective_pieces=defective_pieces,
        waste_quantity=payload.waste_quantity,
        waste_unit=payload.waste_unit,
        layer_material_kg=payload.layer_material_kg,
        beika_kg=payload.beika_kg,
        material_rolls_used=payload.material_rolls_used,
        bundle_count=len(bundle_specs),
        total_bundled_quantity=bundle_total,
        operator_id=payload.operator_id or current.id,
        notes=payload.notes,
    )
    db.add(rec); db.flush()

    # Update work order quantities
    wo.actual_input_qty += cut_pieces
    wo.actual_output_qty += passed_pieces
    wo.passed_qty += passed_pieces
    wo.failed_qty += defective_pieces
    replacement_cut_qty = _allocate_replacement_cut(
        db,
        wo,
        batch_id,
        max(0, passed_pieces - original_remaining_before),
    )
    if replacement_cut_qty > 0:
        db.flush()
    input_quantity = float(payload.input_quantity or 0)
    if payload.fabric_batch_id and input_quantity > 0:
        reserved_consumed = consume_material_reservations_for_stock_batch(
            db,
            production_order_id=int(wo.production_order_id),
            stock_batch_id=int(payload.fabric_batch_id),
            quantity=input_quantity,
            reference_type="CuttingRecord",
            reference_id=rec.id,
            user_id=current.id,
            require_full=require_material_reservation_before_cutting(db),
        )
        direct_quantity = input_quantity - reserved_consumed
        if direct_quantity <= 1e-9:
            direct_quantity = 0.0
    else:
        direct_quantity = 0.0
    if payload.fabric_batch_id and direct_quantity > 0:
        consume_stock_batch(
            db,
            batch_id=payload.fabric_batch_id,
            quantity=direct_quantity,
            unit=payload.input_unit,
            reference_type="CuttingRecord",
            reference_id=rec.id,
            user_id=current.id,
        )
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=payload.fabric_batch_id,
        waste_type="cutting_waste",
        quantity=float(payload.waste_quantity or 0),
        unit=payload.waste_unit,
        reason="Auto-created from cutting record",
        created_by=current.id,
    )

    # Create bundles for the plan
    so_id = po.sales_order_id if po else None
    created_bundles = []
    to_printing = 0
    to_sewing_by_code: dict[str, int] = {}
    for spec in bundle_specs:
        factory_code = spec["factory_code"]
        next_code = spec["next_code"]
        for _ in range(spec["count"]):
            b = create_bundle(
                db,
                production_order_id=wo.production_order_id,
                production_batch_id=batch_id,
                model_id=po.model_id,
                color=spec["color"],
                size=spec["size"],
                quantity=spec["quantity"],
                sales_order_id=so_id,
                next_department_code=next_code,
                sewing_factory_code=factory_code,
                user_id=current.id,
            )
            created_bundles.append({
                "id": b.id,
                "bundle_no": b.bundle_no,
                "barcode": b.barcode,
                "production_batch_id": b.production_batch_id,
                "cutting_record_id": rec.id,
                "color": b.color,
                "size": b.size,
                "quantity": b.quantity,
                "status": b.status,
                "sewing_factory_code": b.sewing_factory_code,
                "created_by": b.created_by,
            })
            if next_code == "PRT":
                to_printing += 1
            else:
                to_sewing_by_code[next_code] = to_sewing_by_code.get(next_code, 0) + 1

    sewing_department_code, _ = sync_textile_departments_for_bundle_route(db, wo.production_order_id, batch_id)
    accessory_plan = sync_sewing_accessory_block(db, int(wo.production_order_id)) if to_sewing_by_code else None
    accessories_ready = bool(accessory_plan.get("is_complete")) if accessory_plan else True
    has_printing_work_order = _context_work_order(db, wo, "printing") is not None
    propagate_cutting_plan_from_output(db, wo)
    advance_workflow(
        db,
        wo,
        trigger_output_qty=passed_pieces,
        allow_next_stage_start=not (to_sewing_by_code and not has_printing_work_order and not accessories_ready),
    )
    if to_printing:
        notify_department(
            db,
            department_code="PRT",
            title="Incoming cutting bundles",
            message=f"{to_printing} bundle(s) ready from order {wo.order_no or wo.id}.",
            link="/bundles/scan/printing",
        )
    if replacement_cut_qty > 0:
        notify_department(
            db,
            department_code=sewing_department_code,
            title="Replacement pieces cut",
            message=(
                f"Order {wo.order_no or wo.id}: {replacement_cut_qty} replacement piece(s) were cut "
                "and are moving back to sewing."
            ),
            link=f"/work-orders/{_context_work_order(db, wo, 'sewing').id}/sewing"
            if _context_work_order(db, wo, "sewing") else "/departments",
        )
    if to_sewing_by_code and not accessories_ready and accessory_plan:
        _notify_accessory_issue_block(db, wo, accessory_plan, "cutting")
    else:
        for department_code, to_sewing in to_sewing_by_code.items():
            target_department_code = sewing_department_code if sewing_department_code in {"MIL", "BST", "ECO"} else department_code
            notify_department(
                db,
                department_code=target_department_code,
                title="Incoming cutting bundles",
                message=f"{to_sewing} bundle(s) ready from order {wo.order_no or wo.id}.",
                link=f"/departments/{target_department_code}",
            )

    log_action(
        db,
        current,
        "create",
        "CuttingRecord",
        rec.id,
        new_value={"bundles": len(created_bundles), "replacement_cut_qty": replacement_cut_qty},
    )
    db.commit(); db.refresh(rec)
    return {"id": rec.id, "bundles": created_bundles, "replacement_cut_qty": replacement_cut_qty}


@router.get("/cutting/records/{rid}")
def get_cutting(rid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    r = db.get(CuttingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id,
        "production_batch_id": r.production_batch_id,
        "work_order_id": r.work_order_id,
        "fabric_batch_id": r.fabric_batch_id,
        "input_quantity": float(r.input_quantity), "cut_pieces": r.cut_pieces, "passed_pieces": r.passed_pieces,
        "defective_pieces": r.defective_pieces, "waste_quantity": float(r.waste_quantity),
        "layer_material_kg": float(r.layer_material_kg or 0),
        "beika_kg": float(r.beika_kg or 0),
        "material_rolls_used": float(r.material_rolls_used or 0),
        "bundle_count": r.bundle_count, "total_bundled_quantity": r.total_bundled_quantity,
        "operator_id": r.operator_id, "notes": r.notes,
    }


@router.get("/cutting/records/{rid}/production-sheet", response_class=HTMLResponse)
def cutting_production_sheet(
    rid: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    bundle_ids: str | None = None,
):
    record = db.get(CuttingRecord, rid)
    if not record:
        raise HTTPException(404, "Cutting record not found")
    raw_ids = [value.strip() for value in str(bundle_ids or "").split(",") if value.strip()]
    try:
        parsed_ids = list(dict.fromkeys(int(value) for value in raw_ids))
    except ValueError:
        raise HTTPException(400, "bundle_ids must be comma-separated integers")
    try:
        return render_cutting_sheet_html(db, record, parsed_ids)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


def _cutting_record_scope_filter(qry, rec: CuttingRecord):
    if rec.production_batch_id is None:
        return qry.filter(CuttingRecord.production_batch_id.is_(None))
    return qry.filter(CuttingRecord.production_batch_id == rec.production_batch_id)


def _bundle_scope_filter(qry, production_order_id: int, production_batch_id: int | None):
    qry = qry.filter(Bundle.production_order_id == production_order_id)
    if production_batch_id is None:
        return qry.filter(Bundle.production_batch_id.is_(None))
    return qry.filter(Bundle.production_batch_id == production_batch_id)


def _sync_cutting_work_order_from_records(db: DbSession, wo: WorkOrder) -> None:
    db.flush()
    cut_sum, passed_sum, defective_sum = (
        db.query(
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
        )
        .filter(CuttingRecord.work_order_id == wo.id)
        .one()
    )
    wo.actual_input_qty = int(cut_sum or 0)
    wo.actual_output_qty = int(passed_sum or 0)
    wo.passed_qty = int(passed_sum or 0)
    wo.failed_qty = int(defective_sum or 0)
    if wo.status not in ("cancelled", "rejected"):
        processed = int(wo.passed_qty or 0) + int(wo.failed_qty or 0)
        planned = int(wo.planned_output_qty or 0)
        now = datetime.now(timezone.utc)
        if planned > 0 and processed >= planned:
            wo.status = "completed"
            if not wo.end_time:
                wo.end_time = now
            if not wo.start_time:
                wo.start_time = now
        elif processed > 0 and wo.status in ("new", "planning", "waiting", "pending", "ready", "collected", "paused"):
            wo.status = "in_progress"
            if not wo.start_time:
                wo.start_time = now


@router.patch("/cutting/records/{rid}/bundle-quantities")
def update_cutting_bundle_quantities(
    rid: int,
    payload: CuttingBundleQuantityUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "cutting.bundles", "*")),
):
    rec = db.get(CuttingRecord, rid)
    if not rec:
        raise HTTPException(404, "Cutting record not found")
    wo = db.get(WorkOrder, rec.work_order_id)
    if not wo or wo.operation != "cutting":
        raise HTTPException(400, "Cutting record is not attached to a cutting work order")

    scoped_record_ids = [
        int(row_id)
        for (row_id,) in _cutting_record_scope_filter(
            db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id == wo.id),
            rec,
        )
        .order_by(CuttingRecord.id.asc())
        .all()
    ]
    if scoped_record_ids != [int(rec.id)]:
        raise HTTPException(409, "Bundle quantity adjustment is available only when the batch has one cutting record")

    rows = payload.bundles or []
    if not rows:
        raise HTTPException(400, "Provide at least one bundle quantity")
    updates: dict[int, int] = {}
    for idx, row in enumerate(rows, start=1):
        bundle_id = int(row.id or 0)
        quantity = int(row.quantity or 0)
        if bundle_id <= 0:
            raise HTTPException(400, f"Bundle row {idx}: bundle id is required")
        if quantity <= 0:
            raise HTTPException(400, f"Bundle row {idx}: quantity must be greater than zero")
        updates[bundle_id] = quantity

    bundles = (
        _bundle_scope_filter(db.query(Bundle), int(wo.production_order_id), rec.production_batch_id)
        .order_by(Bundle.id.asc())
        .with_for_update()
        .all()
    )
    if not bundles:
        raise HTTPException(404, "No bundles found for this cutting batch")
    bundle_ids = {int(bundle.id) for bundle in bundles}
    unknown_ids = sorted(set(updates) - bundle_ids)
    if unknown_ids:
        raise HTTPException(400, f"Bundle(s) do not belong to this cutting batch: {unknown_ids}")

    old_bundle_rows = [
        {
            "id": int(bundle.id),
            "bundle_no": bundle.bundle_no,
            "quantity": int(bundle.quantity or 0),
        }
        for bundle in bundles
    ]
    old_total = sum(row["quantity"] for row in old_bundle_rows)

    for bundle in bundles:
        quantity = updates.get(int(bundle.id))
        if quantity is not None:
            bundle.quantity = quantity

    new_total = sum(int(bundle.quantity or 0) for bundle in bundles)
    if new_total < old_total:
        raise HTTPException(400, "Cutting bundle total can only be increased before sewing")

    defective = max(0, int(rec.defective_pieces or 0))
    rec.total_bundled_quantity = new_total
    rec.passed_pieces = new_total
    rec.cut_pieces = max(new_total + defective, int(rec.cut_pieces or 0))
    rec.bundle_count = len(bundles)

    if rec.production_batch_id:
        batch = db.get(ProductionBatch, int(rec.production_batch_id))
        if batch and int(batch.planned_quantity or 0) < new_total:
            batch.planned_quantity = new_total

    _sync_cutting_work_order_from_records(db, wo)
    propagate_cutting_plan_from_output(db, wo)
    sync_production_order_status(db, int(wo.production_order_id))
    new_bundle_rows = [
        {
            "id": int(bundle.id),
            "bundle_no": bundle.bundle_no,
            "quantity": int(bundle.quantity or 0),
        }
        for bundle in bundles
    ]
    log_action(
        db,
        current,
        "adjust_cutting_bundle_quantity",
        "CuttingRecord",
        rec.id,
        old_value={"bundles": old_bundle_rows, "total": old_total},
        new_value={"bundles": new_bundle_rows, "total": new_total},
    )
    db.commit()
    return {
        "id": rec.id,
        "production_batch_id": rec.production_batch_id,
        "cut_pieces": int(rec.cut_pieces or 0),
        "passed_pieces": int(rec.passed_pieces or 0),
        "total_bundled_quantity": int(rec.total_bundled_quantity or 0),
        "bundle_count": int(rec.bundle_count or 0),
        "bundles": new_bundle_rows,
    }


# ===== Printing =====
@router.post("/printing/records", status_code=201)
def post_printing(payload: PrintingRecordIn, db: DbSession, current: User = Depends(require_permissions("printing.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "printing": raise HTTPException(400, "Work order is not a printing operation")
    if wo.status in ("new", "planning", "waiting", "ready", "pending", "paused"):
        raise HTTPException(
            409,
            "Printing work order must be collected first. Set status to 'collected' and add a deadline.",
        )
    if wo.status == "collected":
        wo.status = "in_progress"
        if not wo.start_time:
            wo.start_time = datetime.now(timezone.utc)
    _gate_record_submission(wo)
    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="printing",
    )

    if batch_id is not None:
        cut_wo = _context_work_order(db, wo, "cutting")
        upstream_passed = 0
        if cut_wo:
            upstream_passed = int(
                db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0))
                .filter(
                    CuttingRecord.work_order_id == cut_wo.id,
                    CuttingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        current_input = int(
            db.query(func.coalesce(func.sum(PrintingRecord.input_qty), 0))
            .filter(
                PrintingRecord.work_order_id == wo.id,
                PrintingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        if next_total > upstream_passed:
            raise HTTPException(
                400,
                f"Printing input {next_total} exceeds cutting passed {upstream_passed} for this batch",
            )

    rec_data = payload.model_dump()
    rec_data["production_batch_id"] = batch_id
    rec = PrintingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    wo.failed_qty += payload.rejected_qty
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="printing_reject",
        quantity=float(payload.rejected_qty or 0),
        unit="pcs",
        reason=payload.defect_reason or "Auto-created from printing record",
        created_by=current.id,
    )
    accessory_plan = sync_sewing_accessory_block(db, int(wo.production_order_id)) if int(payload.passed_qty or 0) > 0 else None
    accessories_ready = bool(accessory_plan.get("is_complete")) if accessory_plan else True
    advance_workflow(
        db,
        wo,
        trigger_output_qty=int(payload.passed_qty or 0),
        allow_next_stage_start=accessories_ready,
    )
    if int(payload.passed_qty or 0) > 0:
        sew_wo = _context_work_order(db, wo, "sewing")
        sewing_department_code = sewing_department_code_for_bundle_route(db, wo.production_order_id, batch_id)
        if not accessories_ready and accessory_plan:
            _notify_accessory_issue_block(db, wo, accessory_plan, "printing")
        else:
            notify_department(
                db,
                department_code=sewing_department_code,
                title="Incoming printed pieces",
                message=f"Order {wo.order_no or wo.id} passed {payload.passed_qty} pcs.",
                link=f"/work-orders/{sew_wo.id}/sewing" if sew_wo else f"/departments/{sewing_department_code}",
            )
    log_action(db, current, "create", "PrintingRecord", rec.id, new_value={"work_order_id": wo.id})
    db.commit(); db.refresh(rec)
    return {"id": rec.id}


@router.get("/printing/records/{rid}")
def get_printing(rid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    r = db.get(PrintingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id, "work_order_id": r.work_order_id,
        "production_batch_id": r.production_batch_id,
        "input_qty": r.input_qty, "printed_qty": r.printed_qty,
        "passed_qty": r.passed_qty, "rejected_qty": r.rejected_qty,
        "defect_reason": r.defect_reason, "print_type": r.print_type,
        "operator_id": r.operator_id, "notes": r.notes,
    }


# ===== Sewing =====
def _apply_replacement_sewing_output(
    db: DbSession,
    wo: WorkOrder,
    production_batch_id: int | None,
    passed_qty: int,
) -> int:
    remaining = max(0, int(passed_qty or 0))
    if remaining <= 0:
        return 0
    qry = db.query(SewingReplacementRequest).filter(
        SewingReplacementRequest.sewing_work_order_id == wo.id,
        SewingReplacementRequest.replaced_qty < SewingReplacementRequest.cut_qty,
    )
    if production_batch_id is None:
        qry = qry.filter(SewingReplacementRequest.production_batch_id.is_(None))
    else:
        qry = qry.filter(SewingReplacementRequest.production_batch_id == production_batch_id)
    replaced = 0
    for request in qry.order_by(SewingReplacementRequest.id).all():
        available = max(0, int(request.cut_qty or 0) - int(request.replaced_qty or 0))
        take = min(available, remaining)
        if take <= 0:
            continue
        request.replaced_qty = int(request.replaced_qty or 0) + take
        if request.replaced_qty >= request.requested_qty:
            request.replaced_qty = int(request.requested_qty or 0)
            request.status = "completed"
        else:
            request.status = "waiting_sewing" if request.cut_qty >= request.requested_qty else "waiting_cutting"
        remaining -= take
        replaced += take
        if remaining <= 0:
            break
    return replaced


@router.post("/sewing/records", status_code=201)
def post_sewing(payload: SewingRecordIn, db: DbSession, current: User = Depends(require_permissions("sewing.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing": raise HTTPException(400, "Work order is not a sewing operation")
    ensure_accessories_issued_for_sewing(db, int(wo.production_order_id))
    _gate_record_submission(wo)

    assignment = None
    if payload.sewing_assignment_id:
        assignment = db.get(SewingAssignment, payload.sewing_assignment_id)
        if not assignment:
            raise HTTPException(404, "Sewing assignment not found")
        if assignment.work_order_id != wo.id:
            raise HTTPException(400, "Selected sewing assignment does not belong to this work order")
    elif payload.line_name:
        line_key = payload.line_name.strip().lower()
        if line_key:
            assignment = (
                db.query(SewingAssignment)
                .join(SewingFlow, SewingFlow.id == SewingAssignment.sewing_flow_id)
                .filter(SewingAssignment.work_order_id == wo.id)
                .filter(SewingAssignment.status.in_(["planned", "in_progress", "completed"]))
                .filter(
                    (func.lower(SewingFlow.code) == line_key)
                    | (func.lower(SewingFlow.name) == line_key)
                )
                .order_by(SewingAssignment.id.desc())
                .first()
            )

    payload_batch_id = payload.production_batch_id
    if assignment and assignment.production_batch_id is not None:
        assignment_batch_id = int(assignment.production_batch_id)
        if payload_batch_id and int(payload_batch_id) != assignment_batch_id:
            raise HTTPException(400, "Selected sewing assignment belongs to a different production batch")
        payload_batch_id = assignment_batch_id

    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload_batch_id,
        operation_name="sewing",
    )

    # Rule: sewing cannot receive more than cutting/printing passed
    upstream_passed = 0
    cut_wo = _context_work_order(db, wo, "cutting")
    prt_wo = _context_work_order(db, wo, "printing")
    if batch_id is not None:
        printing_passed = 0
        cutting_passed = 0
        if prt_wo:
            printing_passed = int(
                db.query(func.coalesce(func.sum(PrintingRecord.passed_qty), 0))
                .filter(
                    PrintingRecord.work_order_id == prt_wo.id,
                    PrintingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        if cut_wo:
            cutting_passed = int(
                db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0))
                .filter(
                    CuttingRecord.work_order_id == cut_wo.id,
                    CuttingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        upstream_passed = printing_passed if printing_passed > 0 else cutting_passed
        current_input = int(
            db.query(func.coalesce(func.sum(SewingRecord.input_qty), 0))
            .filter(
                SewingRecord.work_order_id == wo.id,
                SewingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        if next_total > upstream_passed:
            raise HTTPException(400, f"Sewing input {next_total} exceeds upstream passed {upstream_passed} for this batch")
    else:
        if prt_wo and prt_wo.passed_qty > 0:
            upstream_passed = prt_wo.passed_qty
        elif cut_wo:
            upstream_passed = cut_wo.passed_qty
        if upstream_passed and wo.actual_input_qty + payload.input_qty > upstream_passed:
            raise HTTPException(400, f"Sewing input {wo.actual_input_qty + payload.input_qty} exceeds upstream passed {upstream_passed}")

    rec_data = payload.model_dump(exclude={"sewing_assignment_id"})
    rec_data["production_batch_id"] = batch_id
    rec = SewingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    replaced_qty = _apply_replacement_sewing_output(db, wo, batch_id, int(payload.passed_qty or 0))
    if replaced_qty > 0:
        db.flush()
    wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.passed_qty
    wo.passed_qty += payload.passed_qty
    failed_replacement_qty = int(payload.failed_qty or 0) + int(payload.rejected_qty or 0)
    wo.failed_qty += failed_replacement_qty
    wo.rework_qty += payload.rework_qty
    consumed_total = int(payload.passed_qty or 0) + int(payload.failed_qty or 0) + int(payload.rejected_qty or 0)
    if assignment and consumed_total > 0:
        remaining = max(0, int(assignment.quantity or 0) - int(assignment.completed_qty or 0))
        consumed = min(remaining, consumed_total)
        if consumed > 0:
            assignment.completed_qty = int(assignment.completed_qty or 0) + consumed
        if assignment.completed_qty > 0 and assignment.status == "planned":
            assignment.status = "in_progress"
            if not assignment.actual_start:
                assignment.actual_start = datetime.now(timezone.utc)
        if assignment.completed_qty >= int(assignment.quantity or 0):
            assignment.completed_qty = int(assignment.quantity or 0)
            assignment.status = "completed"
            if not assignment.actual_start:
                assignment.actual_start = datetime.now(timezone.utc)
            assignment.actual_end = datetime.now(timezone.utc)
    replacement_request = None
    if failed_replacement_qty > 0:
        cutting_wo = _context_work_order(db, wo, "cutting")
        replacement_request = SewingReplacementRequest(
            production_order_id=wo.production_order_id,
            sewing_work_order_id=wo.id,
            cutting_work_order_id=cutting_wo.id if cutting_wo else None,
            production_batch_id=batch_id,
            sewing_record_id=rec.id,
            requested_qty=failed_replacement_qty,
            defect_reason=payload.defect_reason,
            created_by=current.id,
        )
        db.add(replacement_request)
        if cutting_wo and cutting_wo.status not in {"rejected", "cancelled"}:
            cutting_wo.status = "ready"
            cutting_wo.end_time = None
        if wo.status == "completed":
            wo.status = "in_progress"
            wo.end_time = None
        for downstream_operation in ("packaging", "storage_transfer"):
            downstream = _context_work_order(db, wo, downstream_operation)
            if downstream and downstream.status == "completed":
                downstream.status = "in_progress"
                downstream.end_time = None
        cutting_department = db.get(Department, cutting_wo.department_id) if cutting_wo else None
        if cutting_department:
            notify_department(
                db,
                department_code=cutting_department.code,
                title="Replacement cut required",
                message=(
                    f"Order {wo.order_no or wo.id}: prepare fabric and cut {failed_replacement_qty} "
                    "replacement piece(s) for sewing failures."
                ),
                link=f"/work-orders/{cutting_wo.id}/cutting",
            )
        else:
            notify_department(
                db,
                department_code="PLN",
                title="Replacement cutting route missing",
                message=(
                    f"Order {wo.order_no or wo.id} needs {failed_replacement_qty} replacement piece(s), "
                    "but no cutting work order was found."
                ),
                link=f"/production-orders/{wo.production_order_id}",
            )
        db.flush()
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="sewing_defect",
        quantity=float(failed_replacement_qty),
        unit="pcs",
        reason=payload.defect_reason or "Auto-created from sewing record",
        created_by=current.id,
    )
    packaging_department_code = sync_packaging_department_for_bundle_route(db, wo.production_order_id, batch_id)
    advance_workflow(db, wo, trigger_output_qty=int(payload.passed_qty or 0))
    if int(payload.passed_qty or 0) > 0 or failed_replacement_qty > 0:
        pkg_wo = _context_work_order(db, wo, "packaging")
        message = f"Order {wo.order_no or wo.id} has {payload.passed_qty} pcs ready for packaging."
        if failed_replacement_qty > 0:
            message += (
                f" {failed_replacement_qty} failed piece(s) are being replaced; "
                "keep one package open for them."
            )
        notify_department(
            db,
            department_code=packaging_department_code,
            title="Awaiting packaging",
            message=message,
            link=f"/work-orders/{pkg_wo.id}/packaging" if pkg_wo else "/packages",
        )
    log_action(
        db,
        current,
        "create",
        "SewingRecord",
        rec.id,
        new_value={
            "work_order_id": wo.id,
            "replacement_requested_qty": failed_replacement_qty,
            "replacement_completed_qty": replaced_qty,
        },
    )
    db.commit(); db.refresh(rec)
    return {
        "id": rec.id,
        "replacement_request_id": replacement_request.id if replacement_request else None,
        "replacement_requested_qty": failed_replacement_qty,
        "replacement_completed_qty": replaced_qty,
    }


@router.get("/sewing/records/{rid}")
def get_sewing(rid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    r = db.get(SewingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return {
        "id": r.id, "work_order_id": r.work_order_id,
        "production_batch_id": r.production_batch_id,
        "input_qty": r.input_qty, "sewn_qty": r.sewn_qty,
        "passed_qty": r.passed_qty, "failed_qty": r.failed_qty,
        "rework_qty": r.rework_qty, "rejected_qty": r.rejected_qty,
        "defect_reason": r.defect_reason, "line_name": r.line_name,
        "operator_id": r.operator_id, "notes": r.notes,
    }


# ===== Packaging =====
def _packaging_source_work_order(
    db: DbSession,
    production_order_id: int,
    production_batch_id: int | None,
) -> WorkOrder | None:
    rows = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "sewing",
        )
        .order_by(WorkOrder.id)
        .all()
    )
    if production_batch_id is not None:
        exact = next((row for row in rows if row.production_batch_id == production_batch_id), None)
        if exact:
            return exact
    return next((row for row in rows if row.production_batch_id is None), rows[0] if rows else None)


def _packaging_target_work_order(
    db: DbSession,
    production_order_id: int,
    production_batch_id: int | None,
) -> WorkOrder | None:
    rows = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.production_order_id == production_order_id,
            WorkOrder.operation == "packaging",
        )
        .order_by(WorkOrder.id)
        .all()
    )
    if production_batch_id is not None:
        exact = next((row for row in rows if row.production_batch_id == production_batch_id), None)
        if exact:
            return exact
    return next((row for row in rows if row.production_batch_id is None), rows[0] if rows else None)


def _packaging_sewing_totals(
    db: DbSession,
    source_work_order_id: int,
    production_batch_id: int | None,
) -> tuple[int, int]:
    sewing_query = db.query(func.coalesce(func.sum(SewingRecord.passed_qty), 0)).filter(
        SewingRecord.work_order_id == source_work_order_id,
    )
    receipt_query = db.query(func.coalesce(func.sum(PackagingReceipt.quantity), 0)).filter(
        PackagingReceipt.source_work_order_id == source_work_order_id,
    )
    if production_batch_id is None:
        sewing_query = sewing_query.filter(SewingRecord.production_batch_id.is_(None))
        receipt_query = receipt_query.filter(PackagingReceipt.production_batch_id.is_(None))
    else:
        sewing_query = sewing_query.filter(SewingRecord.production_batch_id == production_batch_id)
        receipt_query = receipt_query.filter(PackagingReceipt.production_batch_id == production_batch_id)
    return int(sewing_query.scalar() or 0), int(receipt_query.scalar() or 0)


def _packaging_bundle_candidates(raw_code: str) -> list[str]:
    code = str(raw_code or "").strip()
    if not code:
        return []
    candidates = [code]
    if "|" in code:
        candidates.extend(part.strip() for part in code.split("|") if part.strip())
    if code.upper().startswith("BUNDLE:"):
        payload = code.split(":", 1)[1]
        candidates.extend(part.strip() for part in payload.split("|") if part.strip())
    return list(dict.fromkeys(candidates))


def _packaging_receipt_payload(db: DbSession, receipt: PackagingReceipt) -> dict:
    po = db.get(ProductionOrder, receipt.production_order_id)
    batch = db.get(ProductionBatch, receipt.production_batch_id) if receipt.production_batch_id else None
    bundle = db.get(Bundle, receipt.bundle_id) if receipt.bundle_id else None
    model = db.get(Model, po.model_id) if po else None
    return {
        "id": receipt.id,
        "work_order_id": receipt.work_order_id,
        "source_work_order_id": receipt.source_work_order_id,
        "production_order_id": receipt.production_order_id,
        "production_batch_id": receipt.production_batch_id,
        "production_no": po.production_no if po else None,
        "order_no": po.order_no if po else None,
        "model_id": po.model_id if po else None,
        "model_code": model.code if model else None,
        "model_name": model.name if model else None,
        "batch_no": batch.batch_no if batch else None,
        "batch_name": batch.name if batch else None,
        "bundle_id": receipt.bundle_id,
        "bundle_no": bundle.bundle_no if bundle else None,
        "size": bundle.size if bundle else None,
        "color": bundle.color if bundle else None,
        "quantity": receipt.quantity,
        "receive_method": receipt.receive_method,
        "received_by": receipt.received_by,
        "notes": receipt.notes,
        "created_at": receipt.created_at,
    }


@router.get("/packaging/receive-options")
def packaging_receive_options(
    db: DbSession,
    _: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    q: str | None = None,
    limit: int = 100,
):
    rows = (
        db.query(
            SewingRecord.work_order_id,
            WorkOrder.production_order_id,
            SewingRecord.production_batch_id,
            func.coalesce(func.sum(SewingRecord.passed_qty), 0),
        )
        .join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id)
        .filter(WorkOrder.operation == "sewing", SewingRecord.passed_qty > 0)
        .group_by(SewingRecord.work_order_id, WorkOrder.production_order_id, SewingRecord.production_batch_id)
        .all()
    )
    po_ids = sorted({int(row[1]) for row in rows})
    po_by_id = {int(po.id): po for po in db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()} if po_ids else {}
    model_ids = sorted({int(po.model_id) for po in po_by_id.values()})
    model_by_id = {int(model.id): model for model in db.query(Model).filter(Model.id.in_(model_ids)).all()} if model_ids else {}
    batch_ids = sorted({int(row[2]) for row in rows if row[2] is not None})
    batch_by_id = {
        int(batch.id): batch for batch in db.query(ProductionBatch).filter(ProductionBatch.id.in_(batch_ids)).all()
    } if batch_ids else {}
    needle = str(q or "").strip().lower()
    options: list[dict] = []
    for source_work_order_id, production_order_id, production_batch_id, sewing_passed in rows:
        target = _packaging_target_work_order(db, int(production_order_id), production_batch_id)
        if not target:
            continue
        _, received = _packaging_sewing_totals(db, int(source_work_order_id), production_batch_id)
        available = max(0, int(sewing_passed or 0) - received)
        if available <= 0:
            continue
        po = po_by_id.get(int(production_order_id))
        model = model_by_id.get(int(po.model_id)) if po else None
        batch = batch_by_id.get(int(production_batch_id)) if production_batch_id is not None else None
        option = {
            "work_order_id": target.id,
            "source_work_order_id": int(source_work_order_id),
            "production_order_id": int(production_order_id),
            "production_batch_id": production_batch_id,
            "production_no": po.production_no if po else None,
            "order_no": po.order_no if po else None,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "batch_no": batch.batch_no if batch else None,
            "batch_name": batch.name if batch else None,
            "sewing_passed": int(sewing_passed or 0),
            "received_quantity": received,
            "available_quantity": available,
        }
        if needle:
            haystack = " ".join(str(value or "") for value in option.values()).lower()
            if needle not in haystack:
                continue
        options.append(option)
    options.sort(key=lambda row: (-int(row["available_quantity"]), -int(row["work_order_id"])))
    return options[: max(1, min(int(limit or 100), 500))]


@router.get("/packaging/receipts")
def packaging_receipts(
    db: DbSession,
    _: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    limit: int = 50,
):
    rows = db.query(PackagingReceipt).order_by(PackagingReceipt.id.desc()).limit(max(1, min(int(limit or 50), 200))).all()
    return [_packaging_receipt_payload(db, row) for row in rows]


@router.get("/packaging/received-orders")
def packaging_received_orders(
    db: DbSession,
    _: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    q: str | None = None,
    limit: int = 200,
):
    receipt_rows = (
        db.query(
            PackagingReceipt.work_order_id,
            PackagingReceipt.production_order_id,
            func.coalesce(func.sum(PackagingReceipt.quantity), 0).label("received_quantity"),
            func.max(PackagingReceipt.created_at).label("last_received_at"),
        )
        .group_by(PackagingReceipt.work_order_id, PackagingReceipt.production_order_id)
        .all()
    )
    work_order_ids = sorted({int(row.work_order_id) for row in receipt_rows})
    production_order_ids = sorted({int(row.production_order_id) for row in receipt_rows})
    if not work_order_ids:
        return []

    record_rows = (
        db.query(
            PackagingRecord.work_order_id,
            func.coalesce(func.sum(PackagingRecord.input_qty), 0).label("packing_input_quantity"),
            func.coalesce(func.sum(PackagingRecord.packed_qty), 0).label("packed_quantity"),
        )
        .filter(PackagingRecord.work_order_id.in_(work_order_ids))
        .group_by(PackagingRecord.work_order_id)
        .all()
    )
    records_by_work_order = {
        int(row.work_order_id): (int(row.packing_input_quantity or 0), int(row.packed_quantity or 0))
        for row in record_rows
    }
    replacement_rows = (
        db.query(
            SewingReplacementRequest.production_order_id,
            func.coalesce(
                func.sum(SewingReplacementRequest.requested_qty - SewingReplacementRequest.replaced_qty),
                0,
            ).label("waiting_replacement_qty"),
        )
        .filter(SewingReplacementRequest.production_order_id.in_(production_order_ids))
        .group_by(SewingReplacementRequest.production_order_id)
        .all()
    )
    replacement_by_production_order = {
        int(row.production_order_id): max(0, int(row.waiting_replacement_qty or 0))
        for row in replacement_rows
    }
    production_orders = db.query(ProductionOrder).filter(ProductionOrder.id.in_(production_order_ids)).all()
    po_by_id = {int(po.id): po for po in production_orders}
    model_ids = sorted({int(po.model_id) for po in production_orders if po.model_id})
    models = db.query(Model).filter(Model.id.in_(model_ids)).all() if model_ids else []
    model_by_id = {int(model.id): model for model in models}
    images_by_po = _work_order_images_by_po(db, production_order_ids)
    needle = str(q or "").strip().lower()
    result: list[dict] = []

    for row in receipt_rows:
        work_order_id = int(row.work_order_id)
        production_order_id = int(row.production_order_id)
        received_quantity = int(row.received_quantity or 0)
        packing_input_quantity, packed_quantity = records_by_work_order.get(work_order_id, (0, 0))
        remaining_quantity = max(0, received_quantity - packing_input_quantity)
        waiting_replacement_quantity = replacement_by_production_order.get(production_order_id, 0)
        if remaining_quantity <= 0 and waiting_replacement_quantity <= 0:
            continue
        po = po_by_id.get(production_order_id)
        model = model_by_id.get(int(po.model_id)) if po and po.model_id else None
        general = (model.details_json or {}).get("general", {}) if model and isinstance(model.details_json, dict) else {}
        variant_no = ""
        if isinstance(general, dict):
            variant_no = str(general.get("variant_no") or general.get("variantNo") or "").strip()
        item = {
            "work_order_id": work_order_id,
            "production_order_id": production_order_id,
            "production_no": po.production_no if po else None,
            "order_no": po.order_no if po else None,
            "model_id": po.model_id if po else None,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "variant_no": variant_no or (model.code if model else None),
            "model_image_url": images_by_po.get(production_order_id, {}).get("model_image_url"),
            "received_quantity": received_quantity,
            "packing_input_quantity": packing_input_quantity,
            "packed_quantity": packed_quantity,
            "remaining_quantity": remaining_quantity,
            "waiting_replacement_quantity": waiting_replacement_quantity,
            "last_received_at": row.last_received_at,
        }
        if needle:
            haystack = " ".join(str(value or "") for value in item.values()).lower()
            if needle not in haystack:
                continue
        result.append(item)

    result.sort(key=lambda item: item["last_received_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return result[: max(1, min(int(limit or 200), 500))]


@router.post("/packaging/receive-from-sewing", status_code=201)
def receive_packaging_from_sewing(
    payload: PackagingReceiveFromSewingIn,
    db: DbSession,
    current: User = Depends(require_permissions("packaging.records", "*")),
):
    bundle: Bundle | None = None
    method = "manual"
    if payload.bundle_code:
        method = "scan"
        for candidate in _packaging_bundle_candidates(payload.bundle_code):
            bundle = db.query(Bundle).filter((Bundle.barcode == candidate) | (Bundle.bundle_no == candidate)).first()
            if bundle:
                break
        if not bundle:
            raise HTTPException(404, "Bundle not found")
        if bundle.status != "received_sewing":
            raise HTTPException(400, "Bundle must be received and completed at sewing before packaging can receive it")
        if db.query(PackagingReceipt.id).filter(PackagingReceipt.bundle_id == bundle.id).first():
            raise HTTPException(409, "Bundle has already been received by packaging")
        target = _packaging_target_work_order(db, int(bundle.production_order_id), bundle.production_batch_id)
        source = _packaging_source_work_order(db, int(bundle.production_order_id), bundle.production_batch_id)
        production_batch_id = bundle.production_batch_id
        quantity = int(bundle.quantity or 0)
    else:
        if not payload.work_order_id:
            raise HTTPException(400, "work_order_id is required for manual receiving")
        target = db.get(WorkOrder, int(payload.work_order_id))
        if not target or target.operation != "packaging":
            raise HTTPException(404, "Packaging work order not found")
        production_batch_id = payload.production_batch_id
        source = _packaging_source_work_order(db, int(target.production_order_id), production_batch_id)
        quantity = int(payload.quantity or 0)
    if not target or not source:
        raise HTTPException(404, "Sewing or packaging work order not found")
    if quantity <= 0:
        raise HTTPException(400, "Receiving quantity must be greater than zero")
    sewing_passed, received = _packaging_sewing_totals(db, int(source.id), production_batch_id)
    available = max(0, sewing_passed - received)
    if quantity > available:
        raise HTTPException(400, f"Receiving quantity {quantity} exceeds {available} pcs available from sewing")

    receipt = PackagingReceipt(
        work_order_id=target.id,
        source_work_order_id=source.id,
        production_order_id=target.production_order_id,
        production_batch_id=production_batch_id,
        bundle_id=bundle.id if bundle else None,
        quantity=quantity,
        receive_method=method,
        received_by=current.id,
        notes=payload.notes,
    )
    db.add(receipt)
    target.actual_input_qty = int(target.actual_input_qty or 0) + quantity
    if target.status in {"new", "planning", "waiting", "pending", "ready"}:
        target.status = "collected"
    db.flush()
    log_action(
        db,
        current,
        "receive_from_sewing",
        "PackagingReceipt",
        receipt.id,
        new_value={
            "production_order_id": target.production_order_id,
            "production_batch_id": production_batch_id,
            "bundle_id": bundle.id if bundle else None,
            "quantity": quantity,
            "method": method,
        },
    )
    db.commit()
    db.refresh(receipt)
    result = _packaging_receipt_payload(db, receipt)
    result["remaining_available"] = max(0, available - quantity)
    return result


@router.post("/packaging/records", status_code=201)
def post_packaging(payload: PackagingRecordIn, db: DbSession, current: User = Depends(require_permissions("packaging.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "packaging": raise HTTPException(400, "Work order is not a packaging operation")
    _gate_record_submission(wo)
    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="packaging",
    )
    uses_receipts = bool(
        db.query(PackagingReceipt.id)
        .filter(PackagingReceipt.work_order_id == wo.id)
        .first()
    )

    sew_wo = _context_work_order(db, wo, "sewing")
    if batch_id is not None:
        sewing_passed = 0
        if sew_wo:
            sewing_passed = int(
                db.query(func.coalesce(func.sum(SewingRecord.passed_qty), 0))
                .filter(
                    SewingRecord.work_order_id == sew_wo.id,
                    SewingRecord.production_batch_id == batch_id,
                )
                .scalar()
                or 0
            )
        current_input = int(
            db.query(func.coalesce(func.sum(PackagingRecord.input_qty), 0))
            .filter(
                PackagingRecord.work_order_id == wo.id,
                PackagingRecord.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        next_total = current_input + int(payload.input_qty or 0)
        receipt_total = int(
            db.query(func.coalesce(func.sum(PackagingReceipt.quantity), 0))
            .filter(
                PackagingReceipt.work_order_id == wo.id,
                PackagingReceipt.production_batch_id == batch_id,
            )
            .scalar()
            or 0
        )
        input_limit = receipt_total if uses_receipts else sewing_passed
        if next_total > input_limit:
            source = "received from sewing" if uses_receipts else "sewing passed"
            raise HTTPException(400, f"Packaging input {next_total} exceeds {source} {input_limit} for this batch")
    else:
        processed_input = int(
            db.query(func.coalesce(func.sum(PackagingRecord.input_qty), 0))
            .filter(PackagingRecord.work_order_id == wo.id)
            .scalar()
            or 0
        )
        receipt_total = int(
            db.query(func.coalesce(func.sum(PackagingReceipt.quantity), 0))
            .filter(PackagingReceipt.work_order_id == wo.id)
            .scalar()
            or 0
        )
        input_limit = receipt_total if uses_receipts else int(sew_wo.passed_qty or 0) if sew_wo else 0
        next_total = processed_input + int(payload.input_qty or 0)
        if next_total > input_limit:
            source = "received from sewing" if uses_receipts else "sewing passed"
            raise HTTPException(400, f"Packaging input {next_total} exceeds {source} {input_limit}")

    rec_data = payload.model_dump()
    rec_data["production_batch_id"] = batch_id
    rec = PackagingRecord(**rec_data)
    rec.operator_id = payload.operator_id or current.id
    db.add(rec)
    db.flush()
    if not uses_receipts:
        wo.actual_input_qty += payload.input_qty
    wo.actual_output_qty += payload.packed_qty
    wo.passed_qty += payload.packed_qty
    wo.failed_qty += payload.damaged_qty
    consume_packaging_materials_from_bom(
        db,
        production_order_id=wo.production_order_id,
        packed_qty=int(payload.packed_qty or 0),
        reference_type="PackagingRecord",
        reference_id=rec.id,
        user_id=current.id,
    )
    create_waste_record(
        db,
        production_order_id=wo.production_order_id,
        work_order_id=wo.id,
        source_department_id=wo.department_id,
        item_id=None,
        batch_id=None,
        waste_type="packaging_damage",
        quantity=float(payload.damaged_qty or 0),
        unit="pcs",
        reason="Auto-created from packaging record",
        created_by=current.id,
    )
    advance_workflow(db, wo, trigger_output_qty=int(payload.packed_qty or 0))
    if int(payload.packed_qty or 0) > 0:
        notify_department(
            db,
            department_code="FGS",
            title="Packed goods ready",
            message=f"Order {wo.order_no or wo.id} packed {payload.packed_qty} pcs and is ready for storage intake.",
            link="/packages/scan",
        )
    log_action(db, current, "create", "PackagingRecord", rec.id, new_value={"work_order_id": wo.id})
    db.commit(); db.refresh(rec)
    return {"id": rec.id}


# ===== Quality =====
@router.post("/quality/checks", response_model=QualityCheckOut, status_code=201)
def post_quality(payload: QualityCheckIn, db: DbSession, current: User = Depends(require_permissions(*_PRODUCTION_FLOOR_PERMS))):
    if not db.get(WorkOrder, payload.work_order_id):
        raise HTTPException(404, "Work order not found")
    q = QualityCheck(**payload.model_dump(), checked_by=current.id, checked_at=datetime.now(timezone.utc))
    db.add(q); db.flush()
    log_action(db, current, "create", "QualityCheck", q.id)
    db.commit(); db.refresh(q)
    return q


@router.get("/quality/checks", response_model=list[QualityCheckOut])
def list_quality(
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    work_order_id: int | None = None,
):
    qry = db.query(QualityCheck)
    if work_order_id: qry = qry.filter(QualityCheck.work_order_id == work_order_id)
    return qry.order_by(QualityCheck.id.desc()).all()
