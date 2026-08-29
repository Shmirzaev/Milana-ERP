import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.deps import DbSession, PRODUCTION_READ_PERMISSIONS, require_permissions, is_admin
from app.core.model_search import model_code_contains
from app.core.signing import sign_path
from app.core.uploads import (
    SAFE_DOCUMENT_EXTENSIONS,
    SAFE_IMAGE_EXTENSIONS,
    extension_for_upload,
    read_validated_upload_content,
    safe_content_type,
)
from app.models import (
    ProductionOrder, ProductionOrderMaterial, WorkOrder, CuttingRecord, CuttingMaterialUsage,
    PrintingRecord, SewingRecord, SewingReplacementRequest,
    PackagingRecord, PackagingReceipt,
    SalesOrder, QualityCheck, User, Department, SewingFlow, SewingAssignment, SewingDailyReport,
    Package, PackageBatchAllocation,
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
from app.services.packaging_scope import (
    packaging_department_scope,
    packaging_work_order_department_code,
    require_packaging_work_order_access,
)
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
from app.services.sewing_scope import sewing_line_factory_scope
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
from app.services.model_images import material_preview_image_url, model_preview_image_url
from app.services.cutting_sheet import render_cutting_sheet_html
from app.services.factory_scope import require_factory_access, selected_factory_code

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


def _require_standard_production_order(db: DbSession, pid: int) -> ProductionOrder:
    po = db.get(ProductionOrder, pid)
    if not po:
        raise HTTPException(404, "Production order not found")
    if po.source_type == "usluga":
        raise HTTPException(409, "Use the isolated Eco Cotton Usluga workflow for this order")
    return po

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


class EditUslugaCuttingBatchIn(BaseModel):
    name: str
    planned_quantity: int | None = None


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
    color: str | None = None
    size: str | None = None


class CuttingBundleQuantityUpdateIn(BaseModel):
    bundles: list[CuttingBundleQuantityRowIn]


class CuttingRecordDetailsUpdateIn(BaseModel):
    layer_material_kg: float | None = None
    beika_kg: float | None = None
    material_rolls_used: float | None = None
    layup_operator_name: str | None = None
    notes: str | None = None


class CuttingBatchUpdateIn(BaseModel):
    name: str | None = None
    planned_quantity: int | None = None
    start_date: datetime | None = None
    deadline: datetime | None = None
    notes: str | None = None


class UslugaBundleSizeCountRowIn(BaseModel):
    color: str
    size: str
    quantity: int = Field(gt=0)


class UslugaBundleSizeCountUpdateIn(BaseModel):
    sizes: list[UslugaBundleSizeCountRowIn]


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
    packaging_department_code: str | None = None


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
    qry = db.query(ProductionOrder).options(joinedload(ProductionOrder.sales_order)).filter(
        ProductionOrder.source_type == "standard"
    )
    if status: qry = qry.filter(ProductionOrder.status == status)
    if production_type: qry = qry.filter(ProductionOrder.production_type == production_type)
    return qry.order_by(ProductionOrder.id.desc()).offset((page - 1) * page_size).limit(page_size).all()


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
        materials=[row.model_dump() for row in payload.materials],
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
        sewing_factory_code=payload.sewing_factory_code,
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
    out["model_code"] = model.code if model else None
    out["model_name"] = model.name if model else None
    out["model_image_url"] = model_preview_image_url(model)
    planned_fabric_batch = db.get(StockBatch, po.fabric_batch_id) if po.fabric_batch_id else None
    # The order workspace is variant-scoped, matching the department inbox
    # card that opened it.  Keep that exact model/BOM picture when available;
    # the selected stock-batch picture remains the fallback and continues to
    # represent that physical batch in inventory and batch-scoped workflows.
    out["material_image_url"] = (
        material_preview_image_url(model)
        or (planned_fabric_batch.image_url if planned_fabric_batch else None)
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
    sewing_work_order = next(
        (row for row in po.work_orders if str(row.operation or "") == "sewing"),
        None,
    )
    sewing_department = (
        db.get(Department, sewing_work_order.department_id)
        if sewing_work_order
        else None
    )
    out["sewing_factory_code"] = resolve_sewing_factory_code(
        sewing_department.code if sewing_department else None,
    )
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
    if ext in SAFE_IMAGE_EXTENSIONS:
        from app.services.image_storage import store_uploaded_image

        stored = await store_uploaded_image(
            file,
            target_dir=settings.SALES_ORDER_FILES_DIR,
            file_url_base="/storage/sales-order-files",
            name_prefix="po_print",
            max_bytes=20 * 1024 * 1024,
        )
        safe_name = stored.file_name
        content_type = stored.content_type
    else:
        os.makedirs(settings.SALES_ORDER_FILES_DIR, exist_ok=True)
        safe_name = f"po_print_{uuid4().hex}{ext}"
        abs_path = os.path.join(settings.SALES_ORDER_FILES_DIR, safe_name)
        content = await read_validated_upload_content(file, ext, 20 * 1024 * 1024)
        with open(abs_path, "wb") as f:
            f.write(content)
        content_type = safe_content_type(ext)
    file_url = f"/storage/sales-order-files/{safe_name}"
    return {
        "file_url": sign_path(file_url),
        "file_name": file.filename or safe_name,
        "content_type": content_type,
    }


@router.get("/production-orders/{pid}", response_model=ProductionOrderDetail)
def get_po(pid: int, db: DbSession, current: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    po = db.get(ProductionOrder, pid)
    if po and po.source_type == "usluga":
        require_factory_access(current, "ECO")
    return _production_order_detail_payload(db, pid)


@router.patch("/production-orders/{pid}", response_model=ProductionOrderOut)
def update_po(pid: int, payload: dict, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    po = _require_standard_production_order(db, pid)
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
    po = _require_standard_production_order(db, pid)

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
    sewing_factory_code: str | None = None,
):
    _require_standard_production_order(db, pid)
    wos = create_work_orders(
        db,
        pid,
        include_printing=include_printing,
        cutting_department_code=cutting_department_code,
        sewing_factory_code=sewing_factory_code,
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
    _require_standard_production_order(db, pid)
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

    po = _require_standard_production_order(db, pid)
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
    current: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
    department_id: int | None = None,
    status: str | None = None,
    production_order_id: int | None = None,
    operation: str | None = None,
    only_active: bool = False,
    unassigned_flow: bool = False,
    only_received_sewing: bool = False,
    sewing_factory_code: str | None = None,
):
    qry = db.query(WorkOrder).options(joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order))
    if selected_factory_code(current) != "ECO":
        qry = qry.filter(~WorkOrder.production_order.has(ProductionOrder.source_type == "usluga"))
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
        factory = sewing_line_factory_scope(current, sewing_factory_code)
        received_po_ids = (
            db.query(Bundle.production_order_id)
            .filter(
                Bundle.status == "received_sewing",
                Bundle.sewing_factory_code == factory,
            )
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
def get_wo(wid: int, db: DbSession, current: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.production_order).joinedload(ProductionOrder.sales_order))
        .filter(WorkOrder.id == wid)
        .first()
    )
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.production_order.source_type == "usluga":
        require_factory_access(current, "ECO")
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
    if db.query(ProductionOrder.source_type).filter(ProductionOrder.id == wo.production_order_id).scalar() == "usluga":
        require_factory_access(current, "ECO")
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


@router.patch("/work-orders/{wid}/batches/{batch_id}")
def update_cutting_batch(
    wid: int,
    batch_id: int,
    payload: CuttingBatchUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "planning.production", "*")),
):
    wo = (
        db.query(WorkOrder)
        .filter(WorkOrder.id == wid)
        .with_for_update(of=WorkOrder)
        .one_or_none()
    )
    if not wo or wo.operation != "cutting":
        raise HTTPException(404, "Cutting work order not found")

    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
    department_code = db.query(Department.code).filter(Department.id == wo.department_id).scalar()
    if str(department_code or "").upper() != "ECT":
        return _update_standard_cutting_batch(db, current, wo, batch_id, payload)

    po = (
        db.query(ProductionOrder)
        .filter(ProductionOrder.id == wo.production_order_id)
        .with_for_update(of=ProductionOrder)
        .one_or_none()
    )
    if not po or po.source_type != "usluga":
        raise HTTPException(409, "This is not an Usluga cutting work order")

    batch = (
        db.query(ProductionBatch)
        .filter(
            ProductionBatch.id == batch_id,
            ProductionBatch.production_order_id == po.id,
        )
        .with_for_update(of=ProductionBatch)
        .one_or_none()
    )
    if not batch:
        raise HTTPException(404, "Production batch not found")

    name = str(payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Batch name is required")
    if len(name) > 128:
        raise HTTPException(400, "Batch name cannot exceed 128 characters")
    current_quantity = int(batch.planned_quantity or 0)
    quantity = current_quantity if payload.planned_quantity is None else int(payload.planned_quantity or 0)
    if quantity <= 0:
        raise HTTPException(400, "Batch quantity must be greater than zero")

    live_bundle_count = db.query(Bundle.id).filter(
        Bundle.production_order_id == po.id,
        Bundle.production_batch_id == batch.id,
    ).count()
    bundled_cutting_record = db.query(CuttingRecord.id).filter(
        CuttingRecord.work_order_id == wo.id,
        CuttingRecord.production_batch_id == batch.id,
        (
            (CuttingRecord.bundle_count > 0)
            | (CuttingRecord.total_bundled_quantity > 0)
        ),
    ).first()
    downstream_activity = (
        db.query(PrintingRecord.id).filter(PrintingRecord.production_batch_id == batch.id).first()
        or db.query(SewingRecord.id).filter(SewingRecord.production_batch_id == batch.id).first()
        or db.query(PackagingRecord.id).filter(PackagingRecord.production_batch_id == batch.id).first()
        or db.query(SewingAssignment.id).filter(SewingAssignment.production_batch_id == batch.id).first()
        or db.query(PackageBatchAllocation.id).filter(PackageBatchAllocation.production_batch_id == batch.id).first()
        or db.query(SewingReplacementRequest.id).filter(SewingReplacementRequest.production_batch_id == batch.id).first()
    )
    quantity_locked = bool(live_bundle_count or bundled_cutting_record or downstream_activity)
    if quantity_locked and quantity != current_quantity:
        raise HTTPException(409, "Batch quantity cannot be edited after bundles or downstream activity exist")

    old_value = {
        "production_order_id": int(po.id),
        "work_order_id": int(wo.id),
        "batch_no": batch.batch_no,
        "name": batch.name,
        "planned_quantity": int(batch.planned_quantity or 0),
    }
    batch.name = name
    if not quantity_locked:
        batch.planned_quantity = quantity
    db.flush()
    log_action(
        db,
        current,
        "edit_usluga_cutting_batch",
        "ProductionBatch",
        batch.id,
        old_value=old_value,
        new_value={
            **old_value,
            "name": batch.name,
            "planned_quantity": int(batch.planned_quantity or 0),
            "name_editable_at_any_stage": True,
            "quantity_locked": quantity_locked,
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
        "bundle_count": int(live_bundle_count or 0),
        "name_editable": True,
        "quantity_editable": not quantity_locked,
        "editable": not quantity_locked,
    }


def _update_standard_cutting_batch(
    db: DbSession,
    current: User,
    wo: WorkOrder,
    batch_id: int,
    payload: CuttingBatchUpdateIn,
):
    po = _require_standard_production_order(db, int(wo.production_order_id))
    batch = (
        db.query(ProductionBatch)
        .filter(
            ProductionBatch.id == batch_id,
            ProductionBatch.production_order_id == po.id,
        )
        .with_for_update(of=ProductionBatch)
        .one_or_none()
    )
    if not batch:
        raise HTTPException(404, "Production batch not found for this cutting work order")

    old_value = {
        "name": batch.name,
        "planned_quantity": int(batch.planned_quantity or 0),
        "start_date": batch.start_date,
        "deadline": batch.deadline,
        "notes": batch.notes,
    }
    fields = payload.model_fields_set
    if "planned_quantity" in fields:
        requested = int(payload.planned_quantity or 0)
        if requested <= 0:
            raise HTTPException(400, "Batch quantity must be greater than zero")
        other_batch_total = int(
            db.query(func.coalesce(func.sum(ProductionBatch.planned_quantity), 0))
            .filter(
                ProductionBatch.production_order_id == po.id,
                ProductionBatch.id != batch.id,
            )
            .scalar()
            or 0
        )
        planning_floor = max(0, int(po.planned_quantity or 0) - other_batch_total)
        physical_floor = max(
            _bundle_total_for_scope(db, int(po.id), int(batch.id)),
            _cutting_output_for_scope(db, wo, int(batch.id)),
            _downstream_committed_quantity(db, int(po.id), int(batch.id)),
        )
        minimum = max(planning_floor, physical_floor)
        if requested < minimum:
            raise HTTPException(
                409,
                f"Batch quantity cannot be lower than the current workflow evidence ({minimum})",
            )
        batch.planned_quantity = requested
    if "name" in fields:
        batch.name = str(payload.name or "").strip() or None
    if "start_date" in fields:
        batch.start_date = payload.start_date
    if "deadline" in fields:
        batch.deadline = payload.deadline
        assignments = db.query(SewingAssignment).filter(
            SewingAssignment.work_order_id.in_(
                db.query(WorkOrder.id).filter(
                    WorkOrder.production_order_id == po.id,
                    WorkOrder.operation == "sewing",
                )
            ),
            SewingAssignment.production_batch_id == batch.id,
            SewingAssignment.status.in_(("planned", "in_progress")),
        ).all()
        for assignment in assignments:
            assignment.planned_end = batch.deadline
    if "notes" in fields:
        batch.notes = str(payload.notes or "").strip() or None

    _reconcile_cutting_workflow_plans(db, wo)
    new_value = {
        "name": batch.name,
        "planned_quantity": int(batch.planned_quantity or 0),
        "start_date": batch.start_date,
        "deadline": batch.deadline,
        "notes": batch.notes,
    }
    log_action(
        db,
        current,
        "update_cutting_batch",
        "ProductionBatch",
        batch.id,
        old_value=old_value,
        new_value=new_value,
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
        "name_editable": True,
        "quantity_editable": True,
        "editable": True,
    }


@router.get("/work-orders/{wid}/cutting-batch-progress")
def cutting_batch_progress(wid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "cutting":
        raise HTTPException(400, "Work order is not a cutting operation")

    po, batches = _ordered_batches_for_work_order(db, wo)
    if not batches:
        return {"work_order_id": wo.id, "items": []}

    rows = (
        db.query(
            CuttingRecord.production_batch_id,
            func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
            func.coalesce(func.sum(CuttingRecord.bundle_count), 0),
            func.coalesce(func.sum(CuttingRecord.total_bundled_quantity), 0),
        )
        .filter(CuttingRecord.work_order_id == wo.id)
        .group_by(CuttingRecord.production_batch_id)
        .all()
    )
    totals_by_batch: dict[int, dict[str, int]] = {}
    for batch_id, cut_sum, passed_sum, defective_sum, bundle_count_sum, bundled_quantity_sum in rows:
        if batch_id is None:
            continue
        totals_by_batch[int(batch_id)] = {
            "cut_pieces": int(cut_sum or 0),
            "passed_pieces": int(passed_sum or 0),
            "defective_pieces": int(defective_sum or 0),
            "recorded_bundle_count": int(bundle_count_sum or 0),
            "recorded_bundled_quantity": int(bundled_quantity_sum or 0),
        }

    live_bundle_counts = {
        int(batch_id): int(bundle_count or 0)
        for batch_id, bundle_count in (
            db.query(Bundle.production_batch_id, func.count(Bundle.id))
            .filter(
                Bundle.production_order_id == po.id,
                Bundle.production_batch_id.is_not(None),
            )
            .group_by(Bundle.production_batch_id)
            .all()
        )
        if batch_id is not None
    }

    items = []
    for b in batches:
        totals = totals_by_batch.get(int(b.id), {})
        passed = int(totals.get("passed_pieces", 0))
        defective = int(totals.get("defective_pieces", 0))
        processed = passed + defective
        planned = int(b.planned_quantity or 0)
        live_bundle_count = int(live_bundle_counts.get(int(b.id), 0))
        has_bundle_evidence = bool(
            live_bundle_count
            or int(totals.get("recorded_bundle_count", 0))
            or int(totals.get("recorded_bundled_quantity", 0))
        )
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
            "bundle_count": live_bundle_count,
            "name_editable": True,
            "quantity_editable": bool(po.source_type != "usluga" or not has_bundle_evidence),
            "editable": bool(po.source_type != "usluga" or not has_bundle_evidence),
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


def _sewing_size_key(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _allocate_sewing_size_plan(rows: list[tuple[str, int]], target_quantity: int) -> list[tuple[str, int]]:
    target = max(0, int(target_quantity or 0))
    total = sum(max(0, int(quantity or 0)) for _, quantity in rows)
    if target <= 0 or total <= 0:
        return [(size, 0) for size, _ in rows]
    if target == total:
        return rows

    allocated: list[dict[str, int | str]] = []
    for index, (size, quantity) in enumerate(rows):
        numerator = target * max(0, int(quantity or 0))
        allocated.append({
            "index": index,
            "size": size,
            "quantity": numerator // total,
            "remainder": numerator % total,
        })
    left = target - sum(int(row["quantity"]) for row in allocated)
    ranked = sorted(allocated, key=lambda row: (-int(row["remainder"]), int(row["index"])))
    for index in range(left):
        ranked[index % len(ranked)]["quantity"] = int(ranked[index % len(ranked)]["quantity"]) + 1
    return [
        (str(row["size"]), int(row["quantity"]))
        for row in sorted(allocated, key=lambda row: int(row["index"]))
    ]


def _sewing_size_plan(db: DbSession, wo: WorkOrder, production_batch_id: int | None) -> list[tuple[str, int]]:
    bundle_query = db.query(
        Bundle.size,
        func.coalesce(func.sum(Bundle.quantity), 0),
    ).filter(
        Bundle.production_order_id == wo.production_order_id,
        Bundle.status != "cancelled",
    )
    if production_batch_id is None:
        bundle_query = bundle_query.filter(Bundle.production_batch_id.is_(None))
    else:
        bundle_query = bundle_query.filter(Bundle.production_batch_id == production_batch_id)
    bundle_rows = [
        (str(size).strip(), int(quantity or 0))
        for size, quantity in bundle_query.group_by(Bundle.size).order_by(Bundle.size).all()
        if str(size or "").strip() and int(quantity or 0) > 0
    ]
    if bundle_rows:
        return bundle_rows

    item_rows = (
        db.query(ProductionOrderItem)
        .filter(ProductionOrderItem.production_order_id == wo.production_order_id)
        .order_by(ProductionOrderItem.id)
        .all()
    )
    totals: dict[str, tuple[str, int]] = {}
    for item in item_rows:
        size = str(item.size or "").strip()
        key = _sewing_size_key(size)
        if not key:
            continue
        display, quantity = totals.get(key, (size, 0))
        totals[key] = (display, quantity + max(0, int(item.planned_quantity or 0)))
    rows = list(totals.values())
    if production_batch_id is None:
        return rows

    batch = db.get(ProductionBatch, production_batch_id)
    if not batch or int(batch.production_order_id) != int(wo.production_order_id):
        raise HTTPException(400, "Selected production batch does not belong to this work order")
    return _allocate_sewing_size_plan(rows, int(batch.planned_quantity or 0))


def _sewing_size_progress_payload(
    db: DbSession,
    wo: WorkOrder,
    production_batch_id: int | None,
) -> dict:
    plan = _sewing_size_plan(db, wo, production_batch_id)
    records_query = db.query(SewingRecord).filter(SewingRecord.work_order_id == wo.id)
    if production_batch_id is None:
        records_query = records_query.filter(SewingRecord.production_batch_id.is_(None))
    else:
        records_query = records_query.filter(SewingRecord.production_batch_id == production_batch_id)

    completed_by_size: dict[str, int] = {}
    total_passed = 0
    allocated_output = 0
    for record in records_query.order_by(SewingRecord.id).all():
        total_passed += max(0, int(record.passed_qty or 0))
        for row in record.size_quantities or []:
            size = str(row.get("size") or "").strip()
            quantity = max(0, int(row.get("quantity") or 0))
            key = _sewing_size_key(size)
            if not key or quantity <= 0:
                continue
            completed_by_size[key] = completed_by_size.get(key, 0) + quantity
            allocated_output += quantity

    items = []
    for size, planned_quantity in plan:
        completed_quantity = completed_by_size.get(_sewing_size_key(size), 0)
        items.append({
            "size": size,
            "planned_quantity": int(planned_quantity or 0),
            "completed_quantity": completed_quantity,
            "remaining_quantity": max(0, int(planned_quantity or 0) - completed_quantity),
        })
    return {
        "work_order_id": wo.id,
        "production_batch_id": production_batch_id,
        "items": items,
        "planned_quantity": sum(int(row["planned_quantity"]) for row in items),
        "completed_quantity": sum(int(row["completed_quantity"]) for row in items),
        "remaining_quantity": max(
            0,
            sum(int(row["planned_quantity"]) for row in items) - total_passed,
        ),
        "unallocated_output_quantity": max(0, total_passed - allocated_output),
    }


@router.get("/work-orders/{wid}/sewing-size-progress")
def sewing_size_progress(
    wid: int,
    db: DbSession,
    production_batch_id: int | None = None,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
    wo = db.get(WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing":
        raise HTTPException(400, "Work order is not a sewing operation")
    return _sewing_size_progress_payload(db, wo, production_batch_id)


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


def _next_usluga_cutting_batch_no(db: DbSession, production_order_id: int) -> str:
    prefix = f"USL-CUT-{int(production_order_id):06d}-"
    existing = db.query(CuttingRecord.cutting_batch_no).filter(
        CuttingRecord.cutting_batch_no.like(f"{prefix}%")
    ).count()
    index = existing + 1
    while True:
        candidate = f"{prefix}{index:03d}"
        if not db.query(CuttingRecord.id).filter(CuttingRecord.cutting_batch_no == candidate).first():
            return candidate
        index += 1


def _usluga_cutting_material(db: DbSession, po: ProductionOrder, model_bom_id: int | None) -> ModelBOM:
    material = db.get(ModelBOM, int(model_bom_id or 0)) if model_bom_id else None
    if not material or int(material.model_id) != int(po.model_id or 0):
        raise HTTPException(400, "Select a fabric from the Usluga model")
    if not material.material_name or material.material_role not in {"main", "secondary"}:
        raise HTTPException(400, "Selected Usluga fabric must have a main or secondary role")
    if material.item_id is not None or material.stock_batch_id is not None:
        raise HTTPException(409, "Usluga fabric must not be linked to inventory")
    return material


def _sync_usluga_material_usage(db: DbSession, po: ProductionOrder) -> None:
    approved_total = (
        db.query(func.coalesce(func.sum(CuttingRecord.input_quantity), 0))
        .join(WorkOrder, WorkOrder.id == CuttingRecord.work_order_id)
        .filter(
            WorkOrder.production_order_id == po.id,
            CuttingRecord.approval_status == "approved",
            CuttingRecord.material_role.in_(("main", "secondary")),
        )
        .scalar()
    )
    po.service_material_usage_kg = approved_total


def _usluga_cutting_record_payload(db: DbSession, record: CuttingRecord) -> dict:
    batch = db.get(ProductionBatch, record.production_batch_id) if record.production_batch_id else None
    bundle_rows = db.query(Bundle).filter(Bundle.cutting_record_id == record.id).order_by(Bundle.id).all()
    size_counts: dict[tuple[str, str], dict] = {}
    for bundle in bundle_rows:
        key = (str(bundle.color or ""), str(bundle.size or ""))
        row = size_counts.setdefault(
            key,
            {
                "color": key[0],
                "size": key[1],
                "quantity": 0,
                "bundle_count": 0,
            },
        )
        row["quantity"] += int(bundle.quantity or 0)
        row["bundle_count"] += 1
    return {
        "id": record.id,
        "cutting_batch_no": record.cutting_batch_no,
        "production_batch_id": record.production_batch_id,
        "production_batch_no": batch.batch_no if batch else None,
        "model_bom_id": record.model_bom_id,
        "material_name": record.material_name_snapshot,
        "material_role": record.material_role,
        "approval_status": record.approval_status,
        "approved_by": record.approved_by,
        "approved_at": record.approved_at,
        "rejection_reason": record.rejection_reason,
        "input_quantity": float(record.input_quantity or 0),
        "input_unit": record.input_unit,
        "cut_pieces": int(record.cut_pieces or 0),
        "report_piece_count": int(record.report_piece_count or 0),
        "passed_pieces": int(record.passed_pieces or 0),
        "waste_quantity": float(record.waste_quantity or 0),
        "waste_unit": record.waste_unit,
        "layer_material_kg": float(record.layer_material_kg or 0),
        "beika_kg": float(record.beika_kg or 0),
        "material_rolls_used": float(record.material_rolls_used or 0),
        "layup_operator_name": record.layup_operator_name,
        "notes": record.notes,
        "bundle_ids": [int(row.id) for row in bundle_rows],
        "bundle_count": len(bundle_rows),
        "size_counts": list(size_counts.values()),
        "created_at": record.created_at,
    }


@router.get("/work-orders/{wid}/usluga-cutting-batches")
def list_usluga_cutting_batches(
    wid: int,
    db: DbSession,
    _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS)),
):
    wo = db.get(WorkOrder, wid)
    if not wo or wo.operation != "cutting":
        raise HTTPException(404, "Usluga cutting work order not found")
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po or po.source_type != "usluga":
        raise HTTPException(409, "This is not an Usluga cutting work order")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(_, db, wo)
    records = db.query(CuttingRecord).filter(CuttingRecord.work_order_id == wo.id).order_by(CuttingRecord.id).all()
    return {"work_order_id": wo.id, "items": [_usluga_cutting_record_payload(db, row) for row in records]}


class RejectUslugaCuttingBatchIn(BaseModel):
    reason: str


class UpdateUslugaReportPiecesIn(BaseModel):
    report_piece_count: int = Field(ge=0)


@router.patch("/cutting/records/{rid}/usluga-report-pieces")
def update_usluga_report_pieces(
    rid: int,
    payload: UpdateUslugaReportPiecesIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    rec = db.query(CuttingRecord).filter(CuttingRecord.id == rid).with_for_update().first()
    if not rec:
        raise HTTPException(404, "Cutting batch not found")
    wo = db.get(WorkOrder, rec.work_order_id)
    po = db.get(ProductionOrder, wo.production_order_id) if wo else None
    if not wo or not po or po.source_type != "usluga" or rec.material_role != "secondary":
        raise HTTPException(409, "Report-only pieces can be edited only for secondary Usluga fabric")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)

    old_count = int(rec.report_piece_count or 0)
    rec.report_piece_count = int(payload.report_piece_count)
    log_action(
        db,
        current,
        "update_usluga_report_pieces",
        "CuttingRecord",
        rec.id,
        old_value={"report_piece_count": old_count},
        new_value={"report_piece_count": int(rec.report_piece_count)},
    )
    db.commit()
    db.refresh(rec)
    return _usluga_cutting_record_payload(db, rec)


@router.patch("/cutting/records/{rid}/usluga-size-counts")
def update_usluga_bundle_size_counts(
    rid: int,
    payload: UslugaBundleSizeCountUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    rec = db.query(CuttingRecord).filter(CuttingRecord.id == rid).with_for_update().first()
    if not rec:
        raise HTTPException(404, "Cutting batch not found")
    wo = db.get(WorkOrder, rec.work_order_id)
    po = db.get(ProductionOrder, wo.production_order_id) if wo else None
    if not wo or wo.operation != "cutting" or not po or po.source_type != "usluga" or rec.material_role != "main":
        raise HTTPException(409, "Size counts can be edited only for a main Usluga cutting batch")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)

    bundles = (
        db.query(Bundle)
        .filter(Bundle.cutting_record_id == rec.id)
        .order_by(Bundle.id.asc())
        .with_for_update()
        .all()
    )
    if not bundles:
        raise HTTPException(409, "This Usluga cutting batch has no bundles")
    bundle_ids = [int(bundle.id) for bundle in bundles]
    if db.query(PackagingReceipt.id).filter(PackagingReceipt.bundle_id.in_(bundle_ids)).first():
        raise HTTPException(409, "Size counts cannot be edited after a bundle has packaging history")

    groups: dict[tuple[str, str], list[Bundle]] = {}
    for bundle in bundles:
        groups.setdefault((str(bundle.color or ""), str(bundle.size or "")), []).append(bundle)

    requested: dict[tuple[str, str], int] = {}
    for index, row in enumerate(payload.sizes or [], start=1):
        key = (str(row.color or "").strip(), str(row.size or "").strip())
        if not key[0] or not key[1]:
            raise HTTPException(400, f"Size row {index}: color and size are required")
        if key in requested:
            raise HTTPException(400, f"Size row {index}: duplicate color and size")
        requested[key] = int(row.quantity)
    if set(requested) != set(groups):
        raise HTTPException(400, "Edit the counts for the existing bundle color and size rows only")

    old_total = sum(int(bundle.quantity or 0) for bundle in bundles)
    new_total = sum(requested.values())
    if new_total != old_total:
        raise HTTPException(400, f"Size counts must keep the batch total at {old_total}")
    for key, group in groups.items():
        if requested[key] < len(group):
            raise HTTPException(
                400,
                f"{key[0]} / {key[1]} must have at least {len(group)} piece(s) for its existing bundles",
            )

    old_size_counts = {
        f"{color}\u241f{size}": sum(int(bundle.quantity or 0) for bundle in group)
        for (color, size), group in groups.items()
    }
    old_bundle_rows = [
        {
            "id": int(bundle.id),
            "bundle_no": bundle.bundle_no,
            "color": bundle.color,
            "size": bundle.size,
            "quantity": int(bundle.quantity or 0),
            "status": bundle.status,
        }
        for bundle in bundles
    ]

    for key, group in groups.items():
        target = requested[key]
        current_group_total = sum(int(bundle.quantity or 0) for bundle in group)
        if target == current_group_total:
            continue
        quotient, remainder = divmod(target, len(group))
        for index, bundle in enumerate(group):
            bundle.quantity = quotient + (1 if index < remainder else 0)

    new_bundle_rows = [
        {
            "id": int(bundle.id),
            "bundle_no": bundle.bundle_no,
            "color": bundle.color,
            "size": bundle.size,
            "quantity": int(bundle.quantity or 0),
            "status": bundle.status,
        }
        for bundle in bundles
    ]
    log_action(
        db,
        current,
        "update_usluga_bundle_size_counts",
        "CuttingRecord",
        rec.id,
        old_value={
            "total": old_total,
            "size_counts": old_size_counts,
            "bundles": old_bundle_rows,
        },
        new_value={
            "total": new_total,
            "size_counts": {f"{color}\u241f{size}": quantity for (color, size), quantity in requested.items()},
            "bundles": new_bundle_rows,
        },
    )
    db.commit()
    db.refresh(rec)
    result = _usluga_cutting_record_payload(db, rec)
    result["bundles"] = new_bundle_rows
    return result


@router.post("/cutting/records", status_code=201)
def post_cutting(payload: CuttingRecordIn, db: DbSession, current: User = Depends(require_permissions("cutting.records", "*"))):
    wo = db.get(WorkOrder, payload.work_order_id)
    if not wo: raise HTTPException(404, "Work order not found")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
    if wo.operation != "cutting": raise HTTPException(400, "Work order is not a cutting operation")
    _gate_record_submission(wo)
    po = db.get(ProductionOrder, wo.production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")
    if po.source_type == "usluga" and (payload.fabric_batch_id is not None or payload.materials):
        raise HTTPException(400, "Usluga material usage is recorded without an inventory batch")
    usluga_material = _usluga_cutting_material(db, po, payload.model_bom_id) if po.source_type == "usluga" else None

    raw_materials = [row.model_dump() for row in payload.materials]
    if not raw_materials and payload.fabric_batch_id and float(payload.input_quantity or 0) > 0:
        raw_materials = [{
            "stock_batch_id": int(payload.fabric_batch_id),
            "quantity": float(payload.input_quantity),
            "unit": payload.input_unit,
        }]

    cutting_materials: list[dict] = []
    seen_material_batches: set[int] = set()
    for index, raw in enumerate(raw_materials, start=1):
        batch_id_value = int(raw.get("stock_batch_id") or 0)
        quantity_value = float(raw.get("quantity") or 0)
        unit_value = str(raw.get("unit") or "").strip()
        if batch_id_value <= 0 or quantity_value <= 0 or not unit_value:
            raise HTTPException(400, f"Cutting material #{index} requires a batch, positive amount, and unit")
        if batch_id_value in seen_material_batches:
            raise HTTPException(400, "The same fabric batch cannot be consumed more than once")
        stock_batch = db.get(StockBatch, batch_id_value)
        item = db.get(Item, stock_batch.item_id) if stock_batch else None
        if not stock_batch:
            raise HTTPException(404, f"Cutting material #{index} inventory batch not found")
        if not item or str(item.category or "").lower() not in {"fabric", "semi_finished"}:
            raise HTTPException(400, f"Cutting material #{index} is not fabric")
        seen_material_batches.add(batch_id_value)
        cutting_materials.append({
            "stock_batch_id": batch_id_value,
            "quantity": quantity_value,
            "unit": unit_value,
        })

    planned_materials = (
        db.query(ProductionOrderMaterial)
        .filter(ProductionOrderMaterial.production_order_id == po.id)
        .order_by(ProductionOrderMaterial.position.asc())
        .all()
    )
    if planned_materials:
        planned_batch_ids = {int(row.stock_batch_id) for row in planned_materials}
        submitted_batch_ids = {int(row["stock_batch_id"]) for row in cutting_materials}
        missing_batch_ids = planned_batch_ids - submitted_batch_ids
        unexpected_batch_ids = submitted_batch_ids - planned_batch_ids
        if missing_batch_ids:
            raise HTTPException(400, "Enter the actual amount used for every planned fabric before creating bundles")
        if unexpected_batch_ids:
            raise HTTPException(400, "Cutting materials must match the fabrics selected in planning")
        planned_units = {int(row.stock_batch_id): str(row.unit or "").strip().lower() for row in planned_materials}
        for row in cutting_materials:
            planned_unit = planned_units.get(int(row["stock_batch_id"]))
            if planned_unit and str(row["unit"]).strip().lower() != planned_unit:
                raise HTTPException(400, "Cutting material unit must match the planned material unit")

    primary_material = cutting_materials[0] if cutting_materials else None

    batch_id = _resolve_record_batch_id(
        db,
        wo,
        payload.production_batch_id,
        operation_name="cutting",
    )

    bundle_specs = _parse_cutting_bundle_specs(payload.bundles or [])
    if po.source_type == "usluga":
        if any(spec["next_code"] == "PRT" for spec in bundle_specs):
            raise HTTPException(400, "Usluga follows the Eco Cotton cutting, sewing, and packaging route")
        for spec in bundle_specs:
            spec["factory_code"] = "ECO"
            spec["next_code"] = "ECO"
        if usluga_material and usluga_material.material_role == "secondary" and bundle_specs:
            raise HTTPException(400, "Secondary fabric batches are report-only and cannot create bundles")
    requested_passed_pieces = max(0, int(payload.passed_pieces or 0))
    defective_pieces = max(0, int(payload.defective_pieces or 0))
    requested_cut_pieces = max(0, int(payload.cut_pieces or 0))
    report_piece_count = max(0, int(payload.report_piece_count or 0))
    bundle_total = sum(b["quantity"] * b["count"] for b in bundle_specs)
    if bundle_specs:
        passed_pieces = bundle_total
        cut_pieces = max(requested_cut_pieces, passed_pieces + defective_pieces)
    else:
        passed_pieces = requested_passed_pieces
        cut_pieces = requested_cut_pieces
    if passed_pieces + defective_pieces > cut_pieces:
        raise HTTPException(400, "Passed and defective pieces cannot exceed cut pieces")
    if usluga_material and usluga_material.material_role == "main" and not bundle_specs:
        raise HTTPException(400, "Main fabric batches require a bundle plan for the cutting passport")
    if usluga_material and usluga_material.material_role == "secondary":
        if cut_pieces or passed_pieces or defective_pieces:
            raise HTTPException(400, "Secondary fabric batches record material only, not product pieces")
    elif report_piece_count:
        raise HTTPException(400, "Report-only pieces can be recorded only for secondary Usluga fabric")

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
        fabric_batch_id=primary_material["stock_batch_id"] if primary_material else payload.fabric_batch_id,
        model_bom_id=usluga_material.id if usluga_material else None,
        cutting_batch_no=_next_usluga_cutting_batch_no(db, po.id) if usluga_material else None,
        material_name_snapshot=usluga_material.material_name if usluga_material else None,
        material_role=usluga_material.material_role if usluga_material else None,
        approval_status="pending" if usluga_material else "approved",
        approved_by=None if usluga_material else current.id,
        approved_at=None if usluga_material else datetime.now(timezone.utc),
        input_quantity=primary_material["quantity"] if primary_material else payload.input_quantity,
        input_unit=primary_material["unit"] if primary_material else payload.input_unit,
        cut_pieces=cut_pieces,
        report_piece_count=report_piece_count,
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
        layup_operator_name=(payload.layup_operator_name or "").strip() or None,
        notes=payload.notes,
    )
    db.add(rec); db.flush()
    for position, material in enumerate(cutting_materials, start=1):
        db.add(CuttingMaterialUsage(
            cutting_record_id=rec.id,
            stock_batch_id=material["stock_batch_id"],
            quantity=material["quantity"],
            unit=material["unit"],
            position=position,
        ))

    # Update work order quantities
    replacement_cut_qty = 0
    if not usluga_material:
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
    for material in cutting_materials:
        input_quantity = float(material["quantity"])
        reserved_consumed = consume_material_reservations_for_stock_batch(
            db,
            production_order_id=int(wo.production_order_id),
            stock_batch_id=int(material["stock_batch_id"]),
            quantity=input_quantity,
            reference_type="CuttingRecord",
            reference_id=rec.id,
            user_id=current.id,
            require_full=require_material_reservation_before_cutting(db),
        )
        direct_quantity = input_quantity - reserved_consumed
        if direct_quantity <= 1e-9:
            direct_quantity = 0.0
        if direct_quantity > 0:
            consume_stock_batch(
                db,
                batch_id=material["stock_batch_id"],
                quantity=direct_quantity,
                unit=material["unit"],
                reference_type="CuttingRecord",
                reference_id=rec.id,
                user_id=current.id,
            )
    if not usluga_material:
        create_waste_record(
            db,
            production_order_id=wo.production_order_id,
            work_order_id=wo.id,
            source_department_id=wo.department_id,
            item_id=None,
            batch_id=primary_material["stock_batch_id"] if len(cutting_materials) == 1 else None,
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
                cutting_record_id=rec.id,
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

    sewing_department_code = "ECO" if usluga_material else sewing_department_code_for_bundle_route(db, wo.production_order_id, batch_id)
    accessory_plan = None
    accessories_ready = True
    if not usluga_material:
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
    if to_printing and not usluga_material:
        notify_department(
            db,
            department_code="PRT",
            title="Incoming cutting bundles",
            message=f"{to_printing} bundle(s) ready from order {wo.order_no or wo.id}.",
            link="/bundles/scan/printing",
        )
    if replacement_cut_qty > 0 and not usluga_material:
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
    if usluga_material:
        pass
    elif to_sewing_by_code and not accessories_ready and accessory_plan:
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
        new_value={
            "bundles": len(created_bundles),
            "replacement_cut_qty": replacement_cut_qty,
            "layup_operator_name": rec.layup_operator_name,
            "cutting_batch_no": rec.cutting_batch_no,
            "material_role": rec.material_role,
            "approval_status": rec.approval_status,
            "report_piece_count": int(rec.report_piece_count or 0),
            "materials": [
                {
                    "stock_batch_id": row["stock_batch_id"],
                    "quantity": row["quantity"],
                    "unit": row["unit"],
                }
                for row in cutting_materials
            ],
        },
    )
    db.commit(); db.refresh(rec)
    return {
        "id": rec.id,
        "bundles": created_bundles,
        "replacement_cut_qty": replacement_cut_qty,
        "cutting_batch_no": rec.cutting_batch_no,
        "material_role": rec.material_role,
        "approval_status": rec.approval_status,
        "report_piece_count": int(rec.report_piece_count or 0),
        "materials": [
            {
                "stock_batch_id": row.stock_batch_id,
                "quantity": float(row.quantity),
                "unit": row.unit,
                "position": row.position,
            }
            for row in rec.materials
        ],
    }


@router.post("/cutting/records/{rid}/approve-usluga-batch")
def approve_usluga_cutting_batch(
    rid: int,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.cutting.approve", "usluga.manage", "*")),
):
    rec = db.query(CuttingRecord).filter(CuttingRecord.id == rid).with_for_update().first()
    if not rec:
        raise HTTPException(404, "Cutting batch not found")
    wo = db.query(WorkOrder).filter(WorkOrder.id == rec.work_order_id).with_for_update().first()
    po = db.get(ProductionOrder, wo.production_order_id) if wo else None
    if not wo or not po or po.source_type != "usluga" or rec.material_role not in {"main", "secondary"}:
        raise HTTPException(409, "This is not an Usluga material batch")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
    if rec.approval_status == "approved":
        return _usluga_cutting_record_payload(db, rec)
    if rec.approval_status == "rejected":
        raise HTTPException(409, "Rejected cutting batches cannot be approved")

    rec.approval_status = "approved"
    rec.approved_by = current.id
    rec.approved_at = datetime.now(timezone.utc)
    rec.rejection_reason = None
    db.flush()
    if rec.material_role == "main":
        bundle_count = db.query(Bundle.id).filter(Bundle.cutting_record_id == rec.id).count()
        if bundle_count <= 0 or int(rec.total_bundled_quantity or 0) <= 0:
            raise HTTPException(409, "Main cutting batch has no passport bundles")
        wo.actual_input_qty = int(wo.actual_input_qty or 0) + int(rec.cut_pieces or 0)
        wo.actual_output_qty = int(wo.actual_output_qty or 0) + int(rec.passed_pieces or 0)
        wo.passed_qty = int(wo.passed_qty or 0) + int(rec.passed_pieces or 0)
        wo.failed_qty = int(wo.failed_qty or 0) + int(rec.defective_pieces or 0)
        create_waste_record(
            db,
            production_order_id=wo.production_order_id,
            work_order_id=wo.id,
            source_department_id=wo.department_id,
            item_id=None,
            batch_id=None,
            waste_type="cutting_waste",
            quantity=float(rec.waste_quantity or 0),
            unit=rec.waste_unit,
            reason=f"Approved Usluga cutting batch {rec.cutting_batch_no}",
            created_by=current.id,
        )
        sync_textile_departments_for_bundle_route(db, wo.production_order_id, rec.production_batch_id)
        propagate_cutting_plan_from_output(db, wo)
        advance_workflow(db, wo, trigger_output_qty=int(rec.passed_pieces or 0), allow_next_stage_start=True)
        notify_department(
            db,
            department_code="ECO",
            title="Approved Usluga cutting batch",
            message=f"{rec.cutting_batch_no}: {int(rec.passed_pieces or 0)} piece(s) ready from {wo.order_no or wo.id}.",
            link="/departments/ECO",
        )
    _sync_usluga_material_usage(db, po)
    if rec.material_role == "secondary":
        # A pending report-only fabric batch deliberately keeps Cutting open.
        # Re-evaluate completion after its explicit approval.
        advance_workflow(db, wo, trigger_output_qty=0, allow_next_stage_start=True)
    log_action(
        db,
        current,
        "approve_usluga_cutting_batch",
        "CuttingRecord",
        rec.id,
        new_value={
            "cutting_batch_no": rec.cutting_batch_no,
            "material_role": rec.material_role,
            "passed_pieces": int(rec.passed_pieces or 0),
            "report_piece_count": int(rec.report_piece_count or 0),
            "input_quantity": float(rec.input_quantity or 0),
        },
    )
    db.commit()
    db.refresh(rec)
    return _usluga_cutting_record_payload(db, rec)


@router.post("/cutting/records/{rid}/reject-usluga-batch")
def reject_usluga_cutting_batch(
    rid: int,
    payload: RejectUslugaCuttingBatchIn,
    db: DbSession,
    current: User = Depends(require_permissions("usluga.cutting.approve", "usluga.manage", "*")),
):
    reason = str(payload.reason or "").strip()
    if not reason:
        raise HTTPException(400, "Rejection reason is required")
    rec = db.query(CuttingRecord).filter(CuttingRecord.id == rid).with_for_update().first()
    if not rec:
        raise HTTPException(404, "Cutting batch not found")
    wo = db.get(WorkOrder, rec.work_order_id)
    po = db.get(ProductionOrder, wo.production_order_id) if wo else None
    if not wo or not po or po.source_type != "usluga" or rec.material_role not in {"main", "secondary"}:
        raise HTTPException(409, "This is not an Usluga material batch")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
    if rec.approval_status == "approved":
        raise HTTPException(409, "Approved cutting batches cannot be rejected")

    was_already_rejected = rec.approval_status == "rejected"
    bundles = (
        db.query(Bundle)
        .filter(Bundle.cutting_record_id == rec.id)
        .with_for_update()
        .order_by(Bundle.id.asc())
        .all()
    )
    allowed_statuses = {"created", "cancelled"} if was_already_rejected else {"created"}
    if any(bundle.status not in allowed_statuses for bundle in bundles):
        raise HTTPException(409, "A bundle from this batch has already moved and cannot be rejected")
    if any(
        str(scan.scan_type or "") != "created"
        for bundle in bundles
        for scan in bundle.scan_logs
    ):
        raise HTTPException(409, "A bundle from this batch has processing history and cannot be rejected")
    bundle_ids = [int(bundle.id) for bundle in bundles]
    if bundle_ids and db.query(PackagingReceipt.id).filter(PackagingReceipt.bundle_id.in_(bundle_ids)).first():
        raise HTTPException(409, "A bundle from this batch has packaging history and cannot be rejected")

    old_value = {
        "cutting_batch_no": rec.cutting_batch_no,
        "production_batch_id": rec.production_batch_id,
        "material_role": rec.material_role,
        "approval_status": rec.approval_status,
        "input_quantity": float(rec.input_quantity or 0),
        "cut_pieces": int(rec.cut_pieces or 0),
        "report_piece_count": int(rec.report_piece_count or 0),
        "passed_pieces": int(rec.passed_pieces or 0),
        "defective_pieces": int(rec.defective_pieces or 0),
        "bundle_ids": bundle_ids,
        "bundle_count": len(bundles),
        "bundled_quantity": sum(int(bundle.quantity or 0) for bundle in bundles),
        "previous_rejection_reason": rec.rejection_reason,
    }
    record_id = int(rec.id)
    cutting_batch_no = rec.cutting_batch_no
    for bundle in bundles:
        db.delete(bundle)
    db.flush()
    db.delete(rec)
    db.flush()
    _sync_usluga_material_usage(db, po)
    advance_workflow(db, wo, trigger_output_qty=0, allow_next_stage_start=True)
    log_action(
        db,
        current,
        "reject_and_delete_usluga_cutting_batch",
        "CuttingRecord",
        record_id,
        old_value=old_value,
        new_value={
            "cutting_batch_no": cutting_batch_no,
            "reason": reason,
            "deleted": True,
            "previously_rejected": was_already_rejected,
        },
    )
    db.commit()
    return {
        "id": record_id,
        "cutting_batch_no": cutting_batch_no,
        "deleted": True,
        "deleted_bundle_count": len(bundles),
        "deleted_bundle_quantity": old_value["bundled_quantity"],
    }


def _cutting_record_payload(r: CuttingRecord) -> dict:
    return {
        "id": r.id,
        "production_batch_id": r.production_batch_id,
        "work_order_id": r.work_order_id,
        "fabric_batch_id": r.fabric_batch_id,
        "materials": [
            {
                "id": row.id,
                "stock_batch_id": row.stock_batch_id,
                "quantity": float(row.quantity),
                "unit": row.unit,
                "position": row.position,
            }
            for row in r.materials
        ],
        "model_bom_id": r.model_bom_id,
        "cutting_batch_no": r.cutting_batch_no,
        "material_name": r.material_name_snapshot,
        "material_role": r.material_role,
        "approval_status": r.approval_status,
        "approved_by": r.approved_by,
        "approved_at": r.approved_at,
        "rejection_reason": r.rejection_reason,
        "input_quantity": float(r.input_quantity), "cut_pieces": r.cut_pieces,
        "report_piece_count": int(r.report_piece_count or 0), "passed_pieces": r.passed_pieces,
        "defective_pieces": r.defective_pieces, "waste_quantity": float(r.waste_quantity),
        "layer_material_kg": float(r.layer_material_kg or 0),
        "beika_kg": float(r.beika_kg or 0),
        "material_rolls_used": float(r.material_rolls_used or 0),
        "bundle_count": r.bundle_count, "total_bundled_quantity": r.total_bundled_quantity,
        "operator_id": r.operator_id,
        "layup_operator_name": r.layup_operator_name,
        "notes": r.notes,
    }


@router.get("/cutting/records/{rid}")
def get_cutting(rid: int, db: DbSession, _: User = Depends(require_permissions(*PRODUCTION_READ_PERMISSIONS))):
    r = db.get(CuttingRecord, rid)
    if not r: raise HTTPException(404, "Not found")
    return _cutting_record_payload(r)


@router.patch("/cutting/records/{rid}")
def update_cutting_record_details(
    rid: int,
    payload: CuttingRecordDetailsUpdateIn,
    db: DbSession,
    current: User = Depends(require_permissions("cutting.records", "*")),
):
    rec = db.query(CuttingRecord).filter(CuttingRecord.id == rid).with_for_update().first()
    if not rec:
        raise HTTPException(404, "Cutting record not found")
    wo = db.get(WorkOrder, rec.work_order_id)
    if not wo or wo.operation != "cutting":
        raise HTTPException(400, "Cutting record is not attached to a cutting work order")
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)

    numeric_fields = ("layer_material_kg", "beika_kg", "material_rolls_used")
    for field in numeric_fields:
        value = getattr(payload, field)
        if value is not None and float(value) < 0:
            raise HTTPException(400, f"{field} cannot be negative")

    old_value = {
        "layer_material_kg": float(rec.layer_material_kg or 0),
        "beika_kg": float(rec.beika_kg or 0),
        "material_rolls_used": float(rec.material_rolls_used or 0),
        "layup_operator_name": rec.layup_operator_name,
        "notes": rec.notes,
    }
    fields = payload.model_fields_set
    for field in numeric_fields:
        if field in fields:
            setattr(rec, field, float(getattr(payload, field) or 0))
    if "layup_operator_name" in fields:
        rec.layup_operator_name = str(payload.layup_operator_name or "").strip() or None
    if "notes" in fields:
        rec.notes = str(payload.notes or "").strip() or None

    new_value = {
        "layer_material_kg": float(rec.layer_material_kg or 0),
        "beika_kg": float(rec.beika_kg or 0),
        "material_rolls_used": float(rec.material_rolls_used or 0),
        "layup_operator_name": rec.layup_operator_name,
        "notes": rec.notes,
    }
    log_action(
        db,
        current,
        "update_cutting_record_details",
        "CuttingRecord",
        rec.id,
        old_value=old_value,
        new_value=new_value,
    )
    db.commit()
    db.refresh(rec)
    return _cutting_record_payload(rec)


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
    po = db.get(ProductionOrder, wo.production_order_id)
    totals_qry = db.query(
        func.coalesce(func.sum(CuttingRecord.cut_pieces), 0),
        func.coalesce(func.sum(CuttingRecord.passed_pieces), 0),
        func.coalesce(func.sum(CuttingRecord.defective_pieces), 0),
    ).filter(CuttingRecord.work_order_id == wo.id)
    if po and po.source_type == "usluga":
        totals_qry = totals_qry.filter(
            CuttingRecord.approval_status == "approved",
            CuttingRecord.material_role == "main",
        )
    cut_sum, passed_sum, defective_sum = totals_qry.one()
    wo.actual_input_qty = int(cut_sum or 0)
    wo.actual_output_qty = int(passed_sum or 0)
    wo.passed_qty = int(passed_sum or 0)
    wo.failed_qty = int(defective_sum or 0)
    if wo.status not in ("cancelled", "rejected"):
        processed = int(wo.passed_qty or 0) + int(wo.failed_qty or 0)
        planned = int(wo.planned_output_qty or 0)
        now = datetime.now(timezone.utc)
        has_pending_usluga = bool(
            po and po.source_type == "usluga" and db.query(CuttingRecord.id).filter(
                CuttingRecord.work_order_id == wo.id,
                CuttingRecord.approval_status == "pending",
            ).first()
        )
        missing_usluga_material = False
        if po and po.source_type == "usluga":
            required_material_ids = {
                int(material_id)
                for (material_id,) in db.query(ModelBOM.id).filter(
                    ModelBOM.model_id == po.model_id,
                    ModelBOM.material_role.in_(("main", "secondary")),
                ).all()
            }
            approved_material_ids = {
                int(material_id)
                for (material_id,) in db.query(CuttingRecord.model_bom_id).filter(
                    CuttingRecord.work_order_id == wo.id,
                    CuttingRecord.approval_status == "approved",
                    CuttingRecord.model_bom_id.is_not(None),
                ).all()
            }
            missing_usluga_material = bool(required_material_ids - approved_material_ids)
        if planned > 0 and processed >= planned and not has_pending_usluga and not missing_usluga_material:
            wo.status = "completed"
            if not wo.end_time:
                wo.end_time = now
            if not wo.start_time:
                wo.start_time = now
        elif processed > 0 and wo.status in ("new", "planning", "waiting", "pending", "ready", "collected", "paused"):
            wo.status = "in_progress"
            if not wo.start_time:
                wo.start_time = now


def _filter_production_batch(qry, column, production_batch_id: int | None):
    if production_batch_id is None:
        return qry.filter(column.is_(None))
    return qry.filter(column == production_batch_id)


def _downstream_committed_quantity(
    db: DbSession,
    production_order_id: int,
    production_batch_id: int | None,
) -> int:
    """Return the strongest persisted downstream quantity for this cutting scope."""
    work_order_ids = [
        int(row_id)
        for (row_id,) in db.query(WorkOrder.id)
        .filter(WorkOrder.production_order_id == production_order_id)
        .all()
    ]
    if not work_order_ids:
        return 0

    evidence = [0]
    printing = _filter_production_batch(
        db.query(
            func.coalesce(func.sum(PrintingRecord.input_qty), 0),
            func.coalesce(func.sum(PrintingRecord.printed_qty), 0),
            func.coalesce(func.sum(PrintingRecord.passed_qty + PrintingRecord.rejected_qty), 0),
        ).filter(PrintingRecord.work_order_id.in_(work_order_ids)),
        PrintingRecord.production_batch_id,
        production_batch_id,
    ).one()
    evidence.extend(int(value or 0) for value in printing)

    sewing = _filter_production_batch(
        db.query(
            func.coalesce(func.sum(SewingRecord.input_qty), 0),
            func.coalesce(func.sum(SewingRecord.sewn_qty), 0),
            func.coalesce(func.sum(SewingRecord.passed_qty + SewingRecord.failed_qty + SewingRecord.rejected_qty), 0),
        ).filter(SewingRecord.work_order_id.in_(work_order_ids)),
        SewingRecord.production_batch_id,
        production_batch_id,
    ).one()
    evidence.extend(int(value or 0) for value in sewing)

    assignment_completed = _filter_production_batch(
        db.query(func.coalesce(func.sum(SewingAssignment.completed_qty), 0)).filter(
            SewingAssignment.work_order_id.in_(work_order_ids),
            SewingAssignment.status != "cancelled",
        ),
        SewingAssignment.production_batch_id,
        production_batch_id,
    ).scalar()
    evidence.append(int(assignment_completed or 0))

    daily_reported = _filter_production_batch(
        db.query(func.coalesce(func.sum(SewingDailyReport.sewn_qty), 0)).filter(
            SewingDailyReport.production_order_id == production_order_id,
        ),
        SewingDailyReport.production_batch_id,
        production_batch_id,
    ).scalar()
    evidence.append(int(daily_reported or 0))

    packaging = _filter_production_batch(
        db.query(
            func.coalesce(func.sum(PackagingRecord.input_qty), 0),
            func.coalesce(func.sum(PackagingRecord.packed_qty + PackagingRecord.damaged_qty), 0),
            func.coalesce(func.sum(PackagingRecord.total_packed_quantity), 0),
        ).filter(PackagingRecord.work_order_id.in_(work_order_ids)),
        PackagingRecord.production_batch_id,
        production_batch_id,
    ).one()
    evidence.extend(int(value or 0) for value in packaging)

    packaging_received = _filter_production_batch(
        db.query(func.coalesce(func.sum(PackagingReceipt.quantity), 0)).filter(
            PackagingReceipt.production_order_id == production_order_id,
        ),
        PackagingReceipt.production_batch_id,
        production_batch_id,
    ).scalar()
    evidence.append(int(packaging_received or 0))

    if production_batch_id is not None:
        allocated = int(
            db.query(func.coalesce(func.sum(PackageBatchAllocation.quantity), 0))
            .join(Package, Package.id == PackageBatchAllocation.package_id)
            .filter(
                Package.production_order_id == production_order_id,
                PackageBatchAllocation.production_batch_id == production_batch_id,
            )
            .scalar()
            or 0
        )
        fallback = int(
            db.query(func.coalesce(func.sum(Package.total_quantity), 0))
            .filter(
                Package.production_order_id == production_order_id,
                Package.production_batch_id == production_batch_id,
                ~Package.id.in_(db.query(PackageBatchAllocation.package_id)),
            )
            .scalar()
            or 0
        )
        evidence.append(allocated + fallback)
    else:
        evidence.append(int(
            db.query(func.coalesce(func.sum(Package.total_quantity), 0))
            .filter(
                Package.production_order_id == production_order_id,
                Package.production_batch_id.is_(None),
                ~Package.id.in_(db.query(PackageBatchAllocation.package_id)),
            )
            .scalar()
            or 0
        ))

    return max(evidence)


def _has_downstream_identity_evidence(
    db: DbSession,
    production_order_id: int,
    production_batch_id: int | None,
) -> bool:
    work_order_ids = db.query(WorkOrder.id).filter(WorkOrder.production_order_id == production_order_id)
    sewing = _filter_production_batch(
        db.query(SewingRecord.id).filter(SewingRecord.work_order_id.in_(work_order_ids)),
        SewingRecord.production_batch_id,
        production_batch_id,
    ).first()
    receipt = _filter_production_batch(
        db.query(PackagingReceipt.id).filter(PackagingReceipt.production_order_id == production_order_id),
        PackagingReceipt.production_batch_id,
        production_batch_id,
    ).first()
    package = _filter_production_batch(
        db.query(Package.id).filter(Package.production_order_id == production_order_id),
        Package.production_batch_id,
        production_batch_id,
    ).first()
    allocation = None
    if production_batch_id is not None:
        allocation = (
            db.query(PackageBatchAllocation.id)
            .join(Package, Package.id == PackageBatchAllocation.package_id)
            .filter(
                Package.production_order_id == production_order_id,
                PackageBatchAllocation.production_batch_id == production_batch_id,
            )
            .first()
        )
    return bool(sewing or receipt or package or allocation)


def _bundle_total_for_scope(
    db: DbSession,
    production_order_id: int,
    production_batch_id: int | None,
) -> int:
    qry = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == production_order_id,
        Bundle.status != "cancelled",
    )
    qry = _filter_production_batch(qry, Bundle.production_batch_id, production_batch_id)
    return int(qry.scalar() or 0)


def _cutting_output_for_scope(
    db: DbSession,
    cutting_wo: WorkOrder,
    production_batch_id: int | None,
) -> int:
    qry = db.query(func.coalesce(func.sum(CuttingRecord.passed_pieces), 0)).filter(
        CuttingRecord.work_order_id == cutting_wo.id,
    )
    qry = _filter_production_batch(qry, CuttingRecord.production_batch_id, production_batch_id)
    passed = int(qry.scalar() or 0)
    replacements = db.query(func.coalesce(func.sum(SewingReplacementRequest.cut_qty), 0)).filter(
        SewingReplacementRequest.cutting_work_order_id == cutting_wo.id,
    )
    replacements = _filter_production_batch(
        replacements,
        SewingReplacementRequest.production_batch_id,
        production_batch_id,
    )
    return max(0, passed - int(replacements.scalar() or 0))


def _planned_quantity_for_scope(
    db: DbSession,
    po: ProductionOrder,
    production_batch_id: int | None,
) -> int:
    if production_batch_id is not None:
        batch = db.get(ProductionBatch, production_batch_id)
        return int(batch.planned_quantity or 0) if batch else 0
    batch_total = int(
        db.query(func.coalesce(func.sum(ProductionBatch.planned_quantity), 0))
        .filter(ProductionBatch.production_order_id == po.id)
        .scalar()
        or 0
    )
    return batch_total if batch_total > 0 else int(po.planned_quantity or 0)


def _reconcile_cutting_workflow_plans(db: DbSession, cutting_wo: WorkOrder) -> None:
    po = db.get(ProductionOrder, cutting_wo.production_order_id)
    if not po:
        return
    db.flush()
    work_orders = db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()
    cutting_by_scope = {
        row.production_batch_id: row
        for row in work_orders
        if row.operation == "cutting"
    }
    fallback_cutting = cutting_by_scope.get(None) or cutting_wo

    for row in work_orders:
        scope_id = int(row.production_batch_id) if row.production_batch_id is not None else None
        scoped_cutting = cutting_by_scope.get(scope_id) or fallback_cutting
        target = max(
            _planned_quantity_for_scope(db, po, scope_id),
            _bundle_total_for_scope(db, int(po.id), scope_id),
            _cutting_output_for_scope(db, scoped_cutting, scope_id),
            _downstream_committed_quantity(db, int(po.id), scope_id),
        )
        own_floor = max(
            int(row.actual_input_qty or 0),
            int(row.actual_output_qty or 0),
            int(row.passed_qty or 0) + int(row.failed_qty or 0),
        )
        target = max(target, own_floor)
        row.planned_input_qty = target
        row.planned_output_qty = target
        if row.status == "completed" and own_floor < target:
            row.status = "in_progress"
            row.end_time = None
            row.start_time = row.start_time or datetime.now(timezone.utc)

    sync_production_order_status(db, int(po.id))


def _sync_sewing_assignments_to_bundle_total(
    db: DbSession,
    sewing_work_order: WorkOrder | None,
    production_batch_id: int | None,
    target_quantity: int,
) -> None:
    if not sewing_work_order:
        return
    qry = db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id == sewing_work_order.id,
        SewingAssignment.status.in_(("planned", "in_progress", "completed")),
    )
    qry = _filter_production_batch(qry, SewingAssignment.production_batch_id, production_batch_id)
    assignments = qry.order_by(SewingAssignment.id.asc()).with_for_update().all()
    if not assignments:
        return

    current_total = sum(int(row.quantity or 0) for row in assignments)
    target = max(0, int(target_quantity or 0))
    if current_total == target:
        return
    if any(row.status == "completed" for row in assignments):
        raise HTTPException(409, "A completed sewing assignment cannot be resized from Cutting")
    completed_total = sum(int(row.completed_qty or 0) for row in assignments)
    if target < completed_total:
        raise HTTPException(409, f"Bundle total cannot be lower than completed sewing quantity ({completed_total})")

    delta = target - current_total
    if delta > 0:
        assignments[-1].quantity = int(assignments[-1].quantity or 0) + delta
        return

    remaining = -delta
    for assignment in reversed(assignments):
        reducible = max(0, int(assignment.quantity or 0) - int(assignment.completed_qty or 0))
        take = min(reducible, remaining)
        assignment.quantity = int(assignment.quantity or 0) - take
        remaining -= take
        if remaining <= 0:
            break
    if remaining > 0:
        raise HTTPException(409, "Sewing assignment progress prevents this bundle reduction")


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
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
    po = db.get(ProductionOrder, int(wo.production_order_id))
    is_usluga = bool(po and po.source_type == "usluga")

    scoped_record_ids = [
        int(row_id)
        for (row_id,) in _cutting_record_scope_filter(
            db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id == wo.id),
            rec,
        )
        .order_by(CuttingRecord.id.asc())
        .all()
    ]
    has_direct_links = db.query(Bundle.id).filter(Bundle.cutting_record_id == rec.id).first() is not None
    if not has_direct_links and scoped_record_ids != [int(rec.id)]:
        raise HTTPException(409, "Bundle quantity adjustment is available only when the batch has one cutting record")

    rows = payload.bundles or []
    if not rows:
        raise HTTPException(400, "Provide at least one bundle quantity")
    updates: dict[int, dict] = {}
    for idx, row in enumerate(rows, start=1):
        bundle_id = int(row.id or 0)
        quantity = int(row.quantity or 0)
        if bundle_id <= 0:
            raise HTTPException(400, f"Bundle row {idx}: bundle id is required")
        if quantity <= 0:
            raise HTTPException(400, f"Bundle row {idx}: quantity must be greater than zero")
        color = str(row.color or "").strip() if row.color is not None else None
        size = str(row.size or "").strip() if row.size is not None else None
        if row.color is not None and not color:
            raise HTTPException(400, f"Bundle row {idx}: color is required")
        if row.size is not None and not size:
            raise HTTPException(400, f"Bundle row {idx}: size is required")
        if is_usluga and (color is not None or size is not None):
            raise HTTPException(409, "Use the isolated Usluga size-count editor for color and size changes")
        updates[bundle_id] = {"quantity": quantity, "color": color, "size": size}

    bundle_qry = db.query(Bundle).filter(Bundle.cutting_record_id == rec.id) if has_direct_links else _bundle_scope_filter(
        db.query(Bundle), int(wo.production_order_id), rec.production_batch_id,
    )
    bundles = (
        bundle_qry
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
            "color": bundle.color,
            "size": bundle.size,
        }
        for bundle in bundles
    ]
    old_total = sum(row["quantity"] for row in old_bundle_rows)

    identity_changed = any(
        (update["color"] is not None and update["color"] != bundle.color)
        or (update["size"] is not None and update["size"] != bundle.size)
        for bundle in bundles
        if (update := updates.get(int(bundle.id))) is not None
    )
    if identity_changed and _has_downstream_identity_evidence(
        db,
        int(wo.production_order_id),
        rec.production_batch_id,
    ):
        raise HTTPException(
            409,
            "Color and size cannot be changed after sewn or packaged output is recorded",
        )

    for bundle in bundles:
        update = updates.get(int(bundle.id))
        if update is not None:
            bundle.quantity = int(update["quantity"])
            if update["color"] is not None:
                bundle.color = update["color"]
            if update["size"] is not None:
                bundle.size = update["size"]

    new_total = sum(int(bundle.quantity or 0) for bundle in bundles)
    downstream_floor = _downstream_committed_quantity(
        db,
        int(wo.production_order_id),
        rec.production_batch_id,
    )
    if is_usluga and new_total < old_total:
        raise HTTPException(400, "Cutting bundle total can only be increased before sewing")
    if not is_usluga and new_total < downstream_floor:
        raise HTTPException(
            409,
            f"Bundle total cannot be lower than recorded downstream output ({downstream_floor})",
        )

    if not is_usluga:
        sewing_wo = _context_work_order(db, wo, "sewing")
        _sync_sewing_assignments_to_bundle_total(db, sewing_wo, rec.production_batch_id, new_total)

    defective = max(0, int(rec.defective_pieces or 0))
    rec.total_bundled_quantity = new_total
    rec.passed_pieces = new_total
    rec.cut_pieces = max(new_total + defective, int(rec.cut_pieces or 0))
    rec.bundle_count = len(bundles)

    if rec.production_batch_id:
        batch = db.get(ProductionBatch, int(rec.production_batch_id))
        if batch and is_usluga and int(batch.planned_quantity or 0) < new_total:
            batch.planned_quantity = new_total
        elif batch and po:
            other_batch_total = int(
                db.query(func.coalesce(func.sum(ProductionBatch.planned_quantity), 0))
                .filter(
                    ProductionBatch.production_order_id == po.id,
                    ProductionBatch.id != batch.id,
                )
                .scalar()
                or 0
            )
            planning_floor = max(0, int(po.planned_quantity or 0) - other_batch_total)
            batch.planned_quantity = max(planning_floor, downstream_floor, new_total)

    _sync_cutting_work_order_from_records(db, wo)
    if is_usluga:
        propagate_cutting_plan_from_output(db, wo)
        sync_production_order_status(db, int(wo.production_order_id))
    else:
        _reconcile_cutting_workflow_plans(db, wo)
    new_bundle_rows = [
        {
            "id": int(bundle.id),
            "bundle_no": bundle.bundle_no,
            "quantity": int(bundle.quantity or 0),
            "color": bundle.color,
            "size": bundle.size,
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
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
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
def _validated_sewing_size_quantities(
    db: DbSession,
    wo: WorkOrder,
    production_batch_id: int | None,
    payload: SewingRecordIn,
) -> list[dict[str, int | str]]:
    if not payload.size_quantities:
        return []

    submitted: dict[str, dict[str, int | str]] = {}
    for row in payload.size_quantities:
        size = str(row.size or "").strip()
        key = _sewing_size_key(size)
        if not key:
            raise HTTPException(400, "Each sewing size must have a name")
        existing = submitted.get(key)
        if existing:
            existing["quantity"] = int(existing["quantity"]) + int(row.quantity)
        else:
            submitted[key] = {"size": size, "quantity": int(row.quantity)}

    size_total = sum(int(row["quantity"]) for row in submitted.values())
    if size_total != int(payload.passed_qty or 0):
        raise HTTPException(400, "Sewing size quantities must equal the passed output quantity")

    progress = _sewing_size_progress_payload(db, wo, production_batch_id)
    if size_total > int(progress["remaining_quantity"] or 0):
        raise HTTPException(
            400,
            f"Sewing size output {size_total} exceeds total remaining {progress['remaining_quantity']}",
        )
    planned_by_size = {
        _sewing_size_key(str(row["size"])): row
        for row in progress["items"]
    }
    if planned_by_size:
        unknown_sizes = [str(row["size"]) for key, row in submitted.items() if key not in planned_by_size]
        if unknown_sizes:
            raise HTTPException(400, f"Unknown sewing size(s): {', '.join(unknown_sizes)}")
        for key, row in submitted.items():
            plan_row = planned_by_size[key]
            remaining = max(0, int(plan_row["remaining_quantity"] or 0))
            if int(row["quantity"]) > remaining:
                raise HTTPException(
                    400,
                    f"Sewing size {plan_row['size']} quantity {row['quantity']} exceeds remaining {remaining}",
                )
            row["size"] = str(plan_row["size"])

    return list(submitted.values())


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
    from app.services.factory_scope import require_work_order_factory_access
    require_work_order_factory_access(current, db, wo)
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
    size_quantities = _validated_sewing_size_quantities(db, wo, batch_id, payload)

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

    rec_data = payload.model_dump(exclude={"sewing_assignment_id", "size_quantities"})
    rec_data["production_batch_id"] = batch_id
    rec_data["size_quantities"] = size_quantities
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
            "size_quantities": size_quantities,
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
        "size_quantities": r.size_quantities or [],
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
        "packaging_department_code": receipt.packaging_department_code,
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
    current: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    q: str | None = None,
    limit: int = 100,
    packaging_department_code: str | None = None,
):
    department_code = packaging_department_scope(current, packaging_department_code)
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
        if packaging_work_order_department_code(db, target) != department_code:
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
            if needle not in haystack and not model_code_contains(option.get("model_code"), needle):
                continue
        options.append(option)
    options.sort(key=lambda row: (-int(row["available_quantity"]), -int(row["work_order_id"])))
    return options[: max(1, min(int(limit or 100), 500))]


@router.get("/packaging/receipts")
def packaging_receipts(
    db: DbSession,
    current: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    limit: int = 50,
    packaging_department_code: str | None = None,
):
    department_code = packaging_department_scope(current, packaging_department_code)
    rows = (
        db.query(PackagingReceipt)
        .filter(PackagingReceipt.packaging_department_code == department_code)
        .order_by(PackagingReceipt.id.desc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    return [_packaging_receipt_payload(db, row) for row in rows]


@router.get("/packaging/received-orders")
def packaging_received_orders(
    db: DbSession,
    current: User = Depends(require_permissions("packaging.records", "planning.production", "*")),
    q: str | None = None,
    limit: int = 200,
    packaging_department_code: str | None = None,
):
    department_code = packaging_department_scope(current, packaging_department_code)
    receipt_rows = (
        db.query(
            PackagingReceipt.work_order_id,
            PackagingReceipt.production_order_id,
            func.coalesce(func.sum(PackagingReceipt.quantity), 0).label("received_quantity"),
            func.max(PackagingReceipt.created_at).label("last_received_at"),
        )
        .filter(PackagingReceipt.packaging_department_code == department_code)
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
            if needle not in haystack and not model_code_contains(item.get("model_code"), needle):
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
    department_code = packaging_department_scope(current, payload.packaging_department_code)
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
    require_packaging_work_order_access(current, db, target, department_code)
    if quantity <= 0:
        raise HTTPException(400, "Receiving quantity must be greater than zero")
    sewing_passed, received = _packaging_sewing_totals(db, int(source.id), production_batch_id)
    available = max(0, sewing_passed - received)
    if quantity > available:
        raise HTTPException(400, f"Receiving quantity {quantity} exceeds {available} pcs available from sewing")

    receipt = PackagingReceipt(
        packaging_department_code=department_code,
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
    require_packaging_work_order_access(current, db, wo)
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

    if batch_id is not None:
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
        batch = db.get(ProductionBatch, batch_id)
        packaging_plan = int(batch.planned_quantity or 0) if batch else 0
        input_limit = receipt_total if uses_receipts else packaging_plan
        if next_total > input_limit:
            source = "received from sewing" if uses_receipts else "packaging batch plan"
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
        packaging_plan = max(int(wo.planned_input_qty or 0), int(wo.planned_output_qty or 0))
        input_limit = receipt_total if uses_receipts else packaging_plan
        next_total = processed_input + int(payload.input_qty or 0)
        if next_total > input_limit:
            source = "received from sewing" if uses_receipts else "packaging plan"
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
    production_order = db.get(ProductionOrder, wo.production_order_id)
    if int(payload.packed_qty or 0) > 0 and getattr(production_order, "source_type", "standard") != "usluga":
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
