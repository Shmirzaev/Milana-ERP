from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import CurrentUser, DbSession
from app.core.dt import as_utc
from app.models import (
    Bundle,
    Customer,
    Department,
    Package,
    ProductionOrder,
    SalesOrder,
    Shipment,
    StockReservation,
    SewingRecord,
    SewingReplacementRequest,
    WorkOrder,
    ModelBOM,
    ModelImage,
    Model,
    ProductionOrderItem,
    Item,
)
from app.services.bundles import (
    DEFAULT_SEWING_FACTORY_CODE,
    DEPT_BESTTEX,
    DEPT_BESTTEX_PACKAGING,
    DEPT_ECO_COTTON,
    DEPT_ECO_COTTON_CUTTING,
    DEPT_ECO_COTTON_PACKAGING,
    DEPT_MILANA,
    DEPT_SEW,
    resolve_sewing_factory_code,
)
from app.services.model_images import model_display_image_url

router = APIRouter(prefix="/inbox", tags=["inbox"])
_PENDING_WO_STATUSES = ("new", "planning", "ready", "waiting", "pending", "collected", "paused")
_IN_PROGRESS_WO_STATUSES = ("in_progress",)
_DEPT_OPERATION = {
    "CUT": "cutting",
    DEPT_ECO_COTTON_CUTTING: "cutting",
    "PRT": "printing",
    DEPT_SEW: "sewing",
    DEPT_MILANA: "sewing",
    DEPT_BESTTEX: "sewing",
    DEPT_ECO_COTTON: "sewing",
    "PKG": "packaging",
    DEPT_BESTTEX_PACKAGING: "packaging",
    DEPT_ECO_COTTON_PACKAGING: "packaging",
    "FGS": "storage_transfer",
}
_SEWING_LOGISTICS_DEPTS = {DEPT_SEW, DEPT_MILANA, DEPT_BESTTEX, DEPT_ECO_COTTON}
_TEXTILE_MIXED = "MIXED"
_TEXTILE_LABELS = {
    DEPT_MILANA: "Milana",
    DEPT_BESTTEX: "Besttex",
    DEPT_ECO_COTTON: "Eco Cotton",
    _TEXTILE_MIXED: "Multiple factories",
}
_WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]
_MATERIAL_CATEGORIES = ("fabric", "semi_finished")
_CANCELLED_PRODUCTION_STATUSES = ("cancelled",)


def _shipment_type_label(order_type: str | None) -> str:
    mapping = {
        "branded_stock_sale": "from_stock",
        "client_order": "client_order",
    }
    return mapping.get(str(order_type or "").strip(), "standard")


def _resolve_department(db: DbSession, current: CurrentUser, dept: str | None) -> Department:
    if dept:
        found = db.query(Department).filter(Department.code == dept.upper()).first()
        if not found:
            raise HTTPException(404, f"Department {dept} not found")
        return found
    if not current.department_id:
        raise HTTPException(400, "User has no department; pass ?dept=CODE")
    found = db.get(Department, current.department_id)
    if not found:
        raise HTTPException(404, "User department not found")
    return found


def _department_ids_by_code(db: DbSession, codes: set[str]) -> dict[str, int]:
    rows = db.query(Department).filter(Department.code.in_(sorted(codes))).all()
    return {str(row.code): int(row.id) for row in rows}


def _textile_code_from_codes(codes: set[str] | None) -> str | None:
    if not codes:
        return None
    if len(codes) == 1:
        return next(iter(codes))
    return _TEXTILE_MIXED


def _textile_payload(textile_code: str | None) -> dict[str, str | None]:
    if not textile_code:
        return {"textile_code": None, "textile_name": None}
    return {
        "textile_code": textile_code,
        "textile_name": _TEXTILE_LABELS.get(textile_code, textile_code),
    }


def _bundle_textile_code(bundle: Bundle) -> str:
    return resolve_sewing_factory_code(bundle.sewing_factory_code)


def _sewing_textile_indexes(
    db: DbSession,
    production_order_ids: list[int],
) -> tuple[dict[int, set[str]], dict[tuple[int, int], set[str]]]:
    ids = sorted({int(po_id) for po_id in production_order_ids if po_id})
    if not ids:
        return {}, {}
    rows = (
        db.query(Bundle.production_order_id, Bundle.production_batch_id, Bundle.sewing_factory_code)
        .filter(Bundle.production_order_id.in_(ids))
        .all()
    )
    by_po: dict[int, set[str]] = {}
    by_batch: dict[tuple[int, int], set[str]] = {}
    for po_id, batch_id, sewing_factory_code in rows:
        code = resolve_sewing_factory_code(sewing_factory_code)
        po_key = int(po_id)
        by_po.setdefault(po_key, set()).add(code)
        if batch_id is not None:
            by_batch.setdefault((po_key, int(batch_id)), set()).add(code)
    return by_po, by_batch


def _textile_code_for_work_order(
    work_order: WorkOrder,
    department_code_by_id: dict[int, str],
    textile_codes_by_po: dict[int, set[str]],
    textile_codes_by_batch: dict[tuple[int, int], set[str]],
) -> str | None:
    if str(work_order.operation or "") != "sewing":
        return None
    po_id = int(work_order.production_order_id or 0)
    batch_id = int(work_order.production_batch_id) if work_order.production_batch_id is not None else None
    if po_id > 0 and batch_id is not None:
        batch_code = _textile_code_from_codes(textile_codes_by_batch.get((po_id, batch_id)))
        if batch_code:
            return batch_code
    if po_id > 0:
        po_code = _textile_code_from_codes(textile_codes_by_po.get(po_id))
        if po_code:
            return po_code
    department_code = department_code_by_id.get(int(work_order.department_id or 0))
    if department_code in {DEPT_MILANA, DEPT_BESTTEX, DEPT_ECO_COTTON}:
        return department_code
    return DEFAULT_SEWING_FACTORY_CODE


def _textile_codes_for_work_orders(db: DbSession, work_orders: list[WorkOrder]) -> dict[int, str | None]:
    if not work_orders:
        return {}
    po_ids = [int(w.production_order_id) for w in work_orders if w.production_order_id]
    textile_codes_by_po, textile_codes_by_batch = _sewing_textile_indexes(db, po_ids)
    dept_ids = sorted({int(w.department_id) for w in work_orders if w.department_id})
    departments = db.query(Department).filter(Department.id.in_(dept_ids)).all() if dept_ids else []
    department_code_by_id = {int(dept.id): str(dept.code) for dept in departments}
    return {
        int(work_order.id): _textile_code_for_work_order(
            work_order,
            department_code_by_id,
            textile_codes_by_po,
            textile_codes_by_batch,
        )
        for work_order in work_orders
    }


def _sewing_work_order_department_ids(db: DbSession) -> list[int]:
    ids_by_code = _department_ids_by_code(db, _SEWING_LOGISTICS_DEPTS)
    return sorted(set(ids_by_code.values()))


def _previous_work_order(by_op: dict[str, WorkOrder], operation: str) -> WorkOrder | None:
    try:
        idx = _WORKFLOW_SEQUENCE.index(operation)
    except ValueError:
        return None
    for candidate in reversed(_WORKFLOW_SEQUENCE[:idx]):
        found = by_op.get(candidate)
        if found:
            return found
    return None


def _incoming_work_items(
    db: DbSession,
    dept_code: str,
    department_ids: list[int],
    textile_filter: str | None = None,
) -> list[dict]:
    target_operation = _DEPT_OPERATION.get(dept_code)
    if not target_operation:
        return []

    qry = (
        db.query(WorkOrder)
        .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
        .filter(
            WorkOrder.operation == target_operation,
            WorkOrder.status.notin_(["completed", "rejected", "cancelled"]),
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
    )
    if department_ids:
        qry = qry.filter(WorkOrder.department_id.in_(department_ids))
    target_rows = qry.order_by(WorkOrder.id.desc()).limit(500).all()
    textile_by_work_order_id = _textile_codes_for_work_orders(db, target_rows)
    if textile_filter:
        target_rows = [
            row
            for row in target_rows
            if textile_by_work_order_id.get(int(row.id)) == textile_filter
        ]
    po_ids = [int(w.production_order_id) for w in target_rows]
    if not po_ids:
        return []

    all_rows = db.query(WorkOrder).filter(WorkOrder.production_order_id.in_(po_ids)).all()
    by_po: dict[int, dict[str, WorkOrder]] = {}
    for row in all_rows:
        by_po.setdefault(int(row.production_order_id), {})[str(row.operation)] = row

    po_rows = db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()
    po_by_id = {int(po.id): po for po in po_rows}
    material_by_po = _material_payload_by_production_order(db, po_ids)
    production_context_by_po = _production_context_by_production_order(db, po_ids)

    incoming: list[dict] = []
    for target in target_rows:
        textile_code = textile_by_work_order_id.get(int(target.id))
        source = _previous_work_order(by_po.get(int(target.production_order_id), {}), target_operation)
        if not source:
            continue
        source_ready_qty = int(source.passed_qty or source.actual_output_qty or 0)
        target_received_qty = int(target.actual_input_qty or 0)
        ready_qty = max(0, source_ready_qty - target_received_qty)
        expected_qty = max(
            ready_qty,
            int(target.planned_input_qty or target.planned_output_qty or 0) - target_received_qty,
        )
        if ready_qty <= 0 and expected_qty <= 0:
            continue
        po = po_by_id.get(int(target.production_order_id))
        incoming.append(
            {
                "production_order_id": target.production_order_id,
                "production_no": po.production_no if po else None,
                "order_no": po.order_no if po else None,
                "sales_order_no": po.sales_order_no if po else None,
                "work_order_id": target.id,
                "source_work_order_id": source.id,
                "source_operation": source.operation,
                "source_status": source.status,
                "target_operation": target.operation,
                "status": target.status,
                "ready_qty": ready_qty,
                "expected_qty": expected_qty,
                "source_passed_qty": source_ready_qty,
                "received_qty": target_received_qty,
                "deadline": target.deadline,
                **_textile_payload(textile_code if target_operation == "sewing" else None),
                **_material_payload_for_po(material_by_po, int(target.production_order_id or 0)),
                **_production_context_for_po(production_context_by_po, int(target.production_order_id or 0)),
            }
        )
    return sorted(incoming, key=lambda row: (0 if int(row["ready_qty"] or 0) > 0 else 1, -int(row["work_order_id"])))[:200]


def _incoming_bundle_groups(db: DbSession, bundles: list[Bundle]) -> list[dict]:
    po_ids = sorted({int(b.production_order_id) for b in bundles if b.production_order_id})
    if not po_ids:
        return []

    po_by_id = {
        int(po.id): po
        for po in (
            db.query(ProductionOrder)
            .filter(
                ProductionOrder.id.in_(po_ids),
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .all()
        )
    }
    material_by_po = _material_payload_by_production_order(db, po_ids)
    production_context_by_po = _production_context_by_production_order(db, po_ids)
    work_rows = db.query(WorkOrder).filter(WorkOrder.production_order_id.in_(po_ids)).all()
    by_po: dict[int, dict[str, WorkOrder]] = {}
    for row in work_rows:
        by_po.setdefault(int(row.production_order_id), {})[str(row.operation)] = row

    grouped: dict[tuple[int, str], dict] = {}
    for b in bundles:
        po_id = int(b.production_order_id or 0)
        if po_id <= 0 or po_id not in po_by_id:
            continue
        textile_code = _bundle_textile_code(b)
        by_op = by_po.get(po_id, {})
        sewing_wo = by_op.get("sewing")
        source = _previous_work_order(by_op, "sewing")
        po = po_by_id.get(po_id)
        group_key = (po_id, textile_code)
        row = grouped.setdefault(
            group_key,
            {
                "production_order_id": po_id,
                "production_no": po.production_no if po else None,
                "order_no": po.order_no if po else None,
                "sales_order_no": po.sales_order_no if po else None,
                "work_order_id": sewing_wo.id if sewing_wo else None,
                "source_work_order_id": source.id if source else None,
                "source_operation": source.operation if source else "cutting",
                "source_status": source.status if source else b.status,
                "target_operation": "sewing",
                "status": sewing_wo.status if sewing_wo else b.status,
                "ready_qty": 0,
                "expected_qty": 0,
                "source_passed_qty": int(source.passed_qty or source.actual_output_qty or 0) if source else 0,
                "received_qty": int(sewing_wo.actual_input_qty or 0) if sewing_wo else 0,
                "deadline": sewing_wo.deadline if sewing_wo else None,
                "bundle_count": 0,
                "bundle_ids": [],
                **_textile_payload(textile_code),
                **_material_payload_for_po(material_by_po, po_id),
                **_production_context_for_po(production_context_by_po, po_id),
            },
        )
        row["bundle_count"] += 1
        row["ready_qty"] += int(b.quantity or 0)
        row["expected_qty"] += int(b.quantity or 0)
        row["bundle_ids"].append(int(b.id))

    return sorted(
        grouped.values(),
        key=lambda row: (-int(row["ready_qty"] or 0), str(row.get("order_no") or row.get("production_no") or ""), -int(row["production_order_id"])),
    )[:200]


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


def _empty_material_payload() -> dict[str, str | int | None]:
    return {
        "material_item_id": None,
        "material_item_sku": None,
        "material_item_name": None,
        "material_image_url": None,
    }


def _material_payload_for_po(material_by_po: dict[int, dict] | None, production_order_id: int | None) -> dict:
    if not material_by_po or not production_order_id:
        return _empty_material_payload()
    return material_by_po.get(int(production_order_id), _empty_material_payload())


def _bom_material_image_url(bom: ModelBOM, item: Item) -> str | None:
    stock_batch = getattr(bom, "stock_batch", None)
    return (
        bom.photo_url
        or getattr(stock_batch, "image_url", None)
        or item.image_url
    )


def _material_payload_by_production_order(db: DbSession, production_order_ids: list[int]) -> dict[int, dict]:
    po_ids = sorted({int(po_id) for po_id in production_order_ids if po_id})
    if not po_ids:
        return {}
    po_rows = db.query(ProductionOrder.id, ProductionOrder.model_id).filter(ProductionOrder.id.in_(po_ids)).all()
    model_by_po = {int(po_id): int(model_id) for po_id, model_id in po_rows if model_id}
    model_ids = sorted(set(model_by_po.values()))
    if not model_ids:
        return {}

    by_model: dict[int, dict] = {}
    bom_rows = (
        db.query(ModelBOM, Item)
        .join(Item, Item.id == ModelBOM.item_id)
        .filter(ModelBOM.model_id.in_(model_ids), Item.category.in_(_MATERIAL_CATEGORIES))
        .order_by(ModelBOM.id.asc())
        .all()
    )
    for bom, item in bom_rows:
        image_url = _bom_material_image_url(bom, item)
        payload = {
            "material_item_id": int(item.id),
            "material_item_sku": item.sku,
            "material_item_name": item.name,
            "material_image_url": image_url,
        }
        existing = by_model.get(int(bom.model_id))
        if not existing or (not existing.get("material_image_url") and image_url):
            by_model[int(bom.model_id)] = payload

    material_images = (
        db.query(ModelImage)
        .filter(ModelImage.model_id.in_(model_ids))
        .order_by(ModelImage.id.desc())
        .all()
    )
    material_image_models: set[int] = set()
    for image in material_images:
        if str(image.image_type or "").lower() != "material":
            continue
        model_id = int(image.model_id)
        if model_id in material_image_models:
            continue
        payload = by_model.setdefault(model_id, _empty_material_payload())
        payload["material_image_url"] = image.file_url
        material_image_models.add(model_id)

    return {
        po_id: by_model.get(model_id, _empty_material_payload())
        for po_id, model_id in model_by_po.items()
    }


def _clean_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_model_code(value: object) -> tuple[str | None, str | None]:
    text = _clean_text(value)
    if not text:
        return None, None
    dash_index = text.rfind("-")
    if 0 < dash_index < len(text) - 1:
        return _clean_text(text[:dash_index]), _clean_text(text[dash_index + 1:])
    return text, None


def _model_general(model: Model | None) -> dict:
    details = model.details_json if model else None
    if not isinstance(details, dict):
        return {}
    general = details.get("general")
    return general if isinstance(general, dict) else {}


def _first_general_text(general: dict, *keys: str) -> str | None:
    for key in keys:
        value = _clean_text(general.get(key))
        if value:
            return value
    return None


def _model_code_parts(model: Model | None) -> tuple[str | None, str | None]:
    code_model_no, code_variant_no = _split_model_code(model.code if model else None)
    general = _model_general(model)
    return (
        _first_general_text(general, "model_no", "modelNo") or code_model_no,
        _first_general_text(general, "variant_no", "variantNo") or code_variant_no,
    )


def _size_summary_from_values(values: list[str]) -> tuple[str | None, int]:
    sizes = list(dict.fromkeys(_clean_text(value) for value in values if _clean_text(value)))
    if not sizes:
        return None, 0
    numeric: list[float] = []
    for size in sizes:
        try:
            numeric.append(float(size))
        except (TypeError, ValueError):
            numeric = []
            break
    if numeric:
        ordered = sorted(numeric)
        first = ordered[0]
        last = ordered[-1]

        def fmt(value: float) -> str:
            return str(int(value)) if float(value).is_integer() else f"{value:g}"

        if len(ordered) == 1:
            return fmt(first), 1
        return f"{fmt(first)}-{fmt(last)} ({len(ordered)})", len(ordered)
    if len(sizes) <= 6:
        return ", ".join(sizes), len(sizes)
    return f"{', '.join(sizes[:6])} +{len(sizes) - 6}", len(sizes)


def _empty_production_context_payload() -> dict:
    return {
        "model_id": None,
        "model_code": None,
        "model_no": None,
        "variant_no": None,
        "model_name": None,
        "model_image_url": None,
        "size_summary": None,
        "size_count": 0,
        "sizes": [],
    }


def _production_context_for_po(context_by_po: dict[int, dict] | None, production_order_id: int | None) -> dict:
    if not context_by_po or not production_order_id:
        return _empty_production_context_payload()
    return context_by_po.get(int(production_order_id), _empty_production_context_payload())


def _production_context_by_production_order(db: DbSession, production_order_ids: list[int]) -> dict[int, dict]:
    po_ids = sorted({int(po_id) for po_id in production_order_ids if po_id})
    if not po_ids:
        return {}

    po_rows = db.query(ProductionOrder.id, ProductionOrder.model_id).filter(ProductionOrder.id.in_(po_ids)).all()
    model_by_po = {int(po_id): int(model_id) for po_id, model_id in po_rows if model_id}
    model_ids = sorted(set(model_by_po.values()))
    model_by_id = {
        int(model.id): model
        for model in db.query(Model).filter(Model.id.in_(model_ids)).all()
    } if model_ids else {}

    sizes_by_po: dict[int, list[str]] = {}
    size_rows = (
        db.query(ProductionOrderItem.production_order_id, ProductionOrderItem.size)
        .filter(ProductionOrderItem.production_order_id.in_(po_ids))
        .order_by(ProductionOrderItem.production_order_id.asc(), ProductionOrderItem.id.asc())
        .all()
    )
    for po_id, size in size_rows:
        value = _clean_text(size)
        if value:
            sizes_by_po.setdefault(int(po_id), []).append(value)

    out: dict[int, dict] = {}
    for po_id in po_ids:
        model_id = model_by_po.get(po_id)
        model = model_by_id.get(model_id or 0)
        model_no, variant_no = _model_code_parts(model)
        sizes = list(dict.fromkeys(sizes_by_po.get(po_id, [])))
        size_summary, size_count = _size_summary_from_values(sizes)
        out[po_id] = {
            "model_id": model_id,
            "model_code": model.code if model else model_no,
            "model_no": model_no,
            "variant_no": variant_no,
            "model_name": model.name if model else None,
            "model_image_url": model_display_image_url(model),
            "size_summary": size_summary,
            "size_count": size_count,
            "sizes": sizes,
        }
    return out


def _work_order_card_payload(
    w: WorkOrder,
    received_by_po: dict[int, dict[str, int]],
    textile_code: str | None = None,
    material_by_po: dict[int, dict] | None = None,
    production_context_by_po: dict[int, dict] | None = None,
) -> dict:
    received = received_by_po.get(int(w.production_order_id), {}) if w.operation == "sewing" else {}
    return {
        "id": w.id,
        "order_no": w.order_no,
        "production_no": w.production_no,
        "sales_order_no": w.sales_order_no,
        "production_order_id": w.production_order_id,
        "operation": w.operation,
        "status": w.status,
        "planned_output_qty": w.planned_output_qty,
        "actual_input_qty": w.actual_input_qty,
        "passed_qty": w.passed_qty,
        "failed_qty": w.failed_qty,
        "received_bundle_count": int(received.get("received_bundle_count") or 0),
        "received_bundle_qty": int(received.get("received_bundle_qty") or 0),
        "deadline": w.deadline,
        "is_blocked": w.is_blocked,
        "block_reason": w.block_reason,
        **_textile_payload(textile_code if w.operation == "sewing" else None),
        **_material_payload_for_po(material_by_po, int(w.production_order_id or 0)),
        **_production_context_for_po(production_context_by_po, int(w.production_order_id or 0)),
    }


def _replacement_cutting_work_payload(
    db: DbSession,
    department_id: int,
) -> list[dict]:
    rows = (
        db.query(SewingReplacementRequest, WorkOrder, ProductionOrder, SewingRecord)
        .join(WorkOrder, WorkOrder.id == SewingReplacementRequest.cutting_work_order_id)
        .join(ProductionOrder, ProductionOrder.id == SewingReplacementRequest.production_order_id)
        .join(SewingRecord, SewingRecord.id == SewingReplacementRequest.sewing_record_id)
        .filter(
            WorkOrder.department_id == department_id,
            SewingReplacementRequest.status == "waiting_cutting",
            SewingReplacementRequest.cut_qty < SewingReplacementRequest.requested_qty,
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
        .order_by(SewingReplacementRequest.created_at.asc(), SewingReplacementRequest.id.asc())
        .all()
    )
    if not rows:
        return []

    production_order_ids = sorted({int(request.production_order_id) for request, _, _, _ in rows})
    material_by_po = _material_payload_by_production_order(db, production_order_ids)
    production_context_by_po = _production_context_by_production_order(db, production_order_ids)

    return [
        {
            "id": request.id,
            "production_order_id": request.production_order_id,
            "cutting_work_order_id": cutting_work_order.id,
            "sewing_work_order_id": request.sewing_work_order_id,
            "production_batch_id": request.production_batch_id,
            "production_no": production_order.production_no,
            "order_no": production_order.order_no,
            "sales_order_no": production_order.sales_order_no,
            "requested_qty": int(request.requested_qty or 0),
            "cut_qty": int(request.cut_qty or 0),
            "remaining_qty": max(0, int(request.requested_qty or 0) - int(request.cut_qty or 0)),
            "sewing_line_name": sewing_record.line_name,
            "defect_reason": request.defect_reason,
            "created_at": request.created_at,
            **_material_payload_for_po(material_by_po, int(request.production_order_id)),
            **_production_context_for_po(production_context_by_po, int(request.production_order_id)),
        }
        for request, cutting_work_order, production_order, sewing_record in rows
    ]


def _replacement_sewing_work_payload(
    db: DbSession,
    department_ids: list[int],
    textile_filter: str | None,
) -> list[dict]:
    rows = (
        db.query(SewingReplacementRequest, WorkOrder, ProductionOrder)
        .join(WorkOrder, WorkOrder.id == SewingReplacementRequest.sewing_work_order_id)
        .join(ProductionOrder, ProductionOrder.id == SewingReplacementRequest.production_order_id)
        .filter(
            WorkOrder.department_id.in_(department_ids),
            SewingReplacementRequest.status == "waiting_sewing",
            SewingReplacementRequest.replaced_qty < SewingReplacementRequest.cut_qty,
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
        .order_by(SewingReplacementRequest.created_at.asc(), SewingReplacementRequest.id.asc())
        .all()
    )
    if not rows:
        return []

    sewing_work_orders = [sewing_work_order for _, sewing_work_order, _ in rows]
    textile_by_work_order_id = _textile_codes_for_work_orders(db, sewing_work_orders)
    if textile_filter:
        rows = [
            row
            for row in rows
            if textile_by_work_order_id.get(int(row[1].id)) == textile_filter
        ]
    if not rows:
        return []

    production_order_ids = sorted({int(request.production_order_id) for request, _, _ in rows})
    material_by_po = _material_payload_by_production_order(db, production_order_ids)
    production_context_by_po = _production_context_by_production_order(db, production_order_ids)

    return [
        {
            "id": request.id,
            "production_order_id": request.production_order_id,
            "sewing_work_order_id": sewing_work_order.id,
            "production_batch_id": request.production_batch_id,
            "production_no": production_order.production_no,
            "order_no": production_order.order_no,
            "sales_order_no": production_order.sales_order_no,
            "requested_qty": int(request.requested_qty or 0),
            "cut_qty": int(request.cut_qty or 0),
            "replaced_qty": int(request.replaced_qty or 0),
            "remaining_qty": max(0, int(request.cut_qty or 0) - int(request.replaced_qty or 0)),
            "defect_reason": request.defect_reason,
            "created_at": request.created_at,
            **_textile_payload(textile_by_work_order_id.get(int(sewing_work_order.id))),
            **_material_payload_for_po(material_by_po, int(request.production_order_id)),
            **_production_context_for_po(production_context_by_po, int(request.production_order_id)),
        }
        for request, sewing_work_order, production_order in rows
    ]


@router.get("")
def department_inbox(
    db: DbSession,
    current: CurrentUser,
    dept: str | None = None,
    tz: str | None = None,
):
    d = _resolve_department(db, current, dept)
    now = datetime.now(timezone.utc)
    try:
        client_tz = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        client_tz = timezone.utc
    today_client = now.astimezone(client_tz).date()

    textile_filter = d.code if d.code in {DEPT_MILANA, DEPT_BESTTEX, DEPT_ECO_COTTON} else None
    sewing_department_ids = _sewing_work_order_department_ids(db)
    if d.code in _SEWING_LOGISTICS_DEPTS and not sewing_department_ids:
        sewing_department_ids = [int(d.id)]
    inbox_department_ids = sewing_department_ids if d.code in _SEWING_LOGISTICS_DEPTS else [int(d.id)]

    incoming_bundle_statuses = ["sent_to_printing", "sent_to_sewing"]
    if d.code in _SEWING_LOGISTICS_DEPTS:
        incoming_bundle_statuses.append("created")

    incoming_bundle_limit = 500 if textile_filter else 200
    incoming_bundles = (
        db.query(Bundle)
        .join(ProductionOrder, ProductionOrder.id == Bundle.production_order_id)
        .filter(
            Bundle.next_department_id.in_(inbox_department_ids),
            Bundle.status.in_(incoming_bundle_statuses),
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
        .order_by(Bundle.id.desc())
        .limit(incoming_bundle_limit)
        .all()
    )
    if textile_filter:
        incoming_bundles = [
            bundle
            for bundle in incoming_bundles
            if _bundle_textile_code(bundle) == textile_filter
        ][:200]
    bundle_po_ids = [int(b.production_order_id) for b in incoming_bundles]
    bundle_po_by_id = {
        int(po.id): po
        for po in db.query(ProductionOrder).filter(ProductionOrder.id.in_(bundle_po_ids)).all()
    } if bundle_po_ids else {}
    bundle_production_no_by_id = {
        po_id: po.production_no
        for po_id, po in bundle_po_by_id.items()
    }
    bundle_order_no_by_id = {
        po_id: po.order_no
        for po_id, po in bundle_po_by_id.items()
    }
    bundle_sales_order_no_by_id = {
        po_id: po.sales_order_no
        for po_id, po in bundle_po_by_id.items()
    }
    bundle_material_by_po = _material_payload_by_production_order(db, bundle_po_ids)
    bundle_production_context_by_po = _production_context_by_production_order(db, bundle_po_ids)
    incoming_work_orders = _incoming_work_items(db, d.code, inbox_department_ids, textile_filter)
    incoming_bundle_groups = _incoming_bundle_groups(db, incoming_bundles)

    if d.code in _SEWING_LOGISTICS_DEPTS:
        work_orders = (
            db.query(WorkOrder)
            .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
            .filter(
                WorkOrder.operation == "sewing",
                WorkOrder.department_id.in_(inbox_department_ids),
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .order_by(WorkOrder.id.desc())
            .limit(500)
            .all()
        )
    else:
        work_orders = (
            db.query(WorkOrder)
            .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
            .filter(
                WorkOrder.department_id == d.id,
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .order_by(WorkOrder.id.desc())
            .limit(500)
            .all()
        )
    textile_by_work_order_id = _textile_codes_for_work_orders(db, work_orders)
    if textile_filter:
        work_orders = [
            work_order
            for work_order in work_orders
            if textile_by_work_order_id.get(int(work_order.id)) == textile_filter
        ]
    pending_work_orders = [w for w in work_orders if w.status in _PENDING_WO_STATUSES]
    in_progress_work_orders = [w for w in work_orders if w.status in _IN_PROGRESS_WO_STATUSES]
    active = [w for w in work_orders if w.status in (*_PENDING_WO_STATUSES, *_IN_PROGRESS_WO_STATUSES)]
    received_by_po = _received_bundle_totals_by_po(db, [int(w.production_order_id) for w in active if w.operation == "sewing"])
    work_order_po_ids = [int(w.production_order_id) for w in work_orders if w.production_order_id]
    material_by_po = _material_payload_by_production_order(db, work_order_po_ids)
    production_context_by_po = _production_context_by_production_order(db, work_order_po_ids)
    blocked = [w for w in work_orders if bool(w.is_blocked)]
    overdue = [
        w
        for w in work_orders
        if as_utc(w.deadline)
        and w.status not in ("completed", "rejected", "cancelled")
        and as_utc(w.deadline) < now
    ]
    needs_qc = [w for w in work_orders if int(w.failed_qty or 0) > 0]
    done_today = [
        w
        for w in work_orders
        if w.status == "completed"
        and w.end_time
        and as_utc(w.end_time)
        and as_utc(w.end_time).astimezone(client_tz).date() == today_client
    ]
    replacement_cutting_work = (
        _replacement_cutting_work_payload(db, int(d.id))
        if d.code in {"CUT", DEPT_ECO_COTTON_CUTTING}
        else []
    )
    replacement_sewing_work = (
        _replacement_sewing_work_payload(db, inbox_department_ids, textile_filter)
        if d.code in _SEWING_LOGISTICS_DEPTS
        else []
    )
    replacement_work_order_ids = {
        int(row["cutting_work_order_id"])
        for row in replacement_cutting_work
    }
    if replacement_work_order_ids:
        pending_work_orders = [w for w in pending_work_orders if int(w.id) not in replacement_work_order_ids]
        in_progress_work_orders = [w for w in in_progress_work_orders if int(w.id) not in replacement_work_order_ids]
        active = [w for w in active if int(w.id) not in replacement_work_order_ids]

    awaiting_packaging = []
    if d.code in {"PKG", DEPT_BESTTEX_PACKAGING, DEPT_ECO_COTTON_PACKAGING}:
        packaging_dept_id = int(d.id)
        sewing_rows = (
            db.query(WorkOrder)
            .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
            .filter(
                WorkOrder.operation == "sewing",
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .all()
        )
        by_po_sew = {w.production_order_id: int(w.passed_qty or 0) for w in sewing_rows}
        by_po_pkg = {
            w.production_order_id: int(w.passed_qty or 0)
            for w in db.query(WorkOrder).filter(
                WorkOrder.operation == "packaging",
                WorkOrder.department_id == packaging_dept_id,
            ).all()
        }
        packaging_context_by_po = _production_context_by_production_order(db, [int(po_id) for po_id in by_po_sew.keys()])
        for po_id, sewn in by_po_sew.items():
            packaging_wo = (
                db.query(WorkOrder)
                .filter(
                    WorkOrder.production_order_id == po_id,
                    WorkOrder.operation == "packaging",
                    WorkOrder.department_id == packaging_dept_id,
                )
                .first()
            )
            if not packaging_wo:
                continue
            already_packed = by_po_pkg.get(po_id, 0)
            if sewn - already_packed <= 0:
                continue
            po = db.get(ProductionOrder, po_id)
            awaiting_packaging.append(
                {
                    "production_order_id": po_id,
                    "production_no": po.production_no if po else None,
                    "order_no": po.order_no if po else None,
                    "sales_order_no": po.sales_order_no if po else None,
                    "ready_qty": sewn - already_packed,
                    "sewn_passed": sewn,
                    "already_packed": already_packed,
                    **_production_context_for_po(packaging_context_by_po, int(po_id)),
                }
            )

    pending_packages = []
    ready_packages = []
    ready_to_ship = []
    if d.code == "FGS":
        packed = db.query(Package).filter(Package.status == "packed").order_by(Package.id.desc()).limit(200).all()
        packed_so_ids = {int(p.sales_order_id) for p in packed if p.sales_order_id}
        packed_sales_by_id = {
            int(so.id): so
            for so in db.query(SalesOrder).filter(SalesOrder.id.in_(packed_so_ids)).all()
        } if packed_so_ids else {}
        pending_packages = [
            {
                "id": p.id,
                "package_no": p.package_no,
                "sales_order_id": p.sales_order_id,
                "sales_order_no": packed_sales_by_id.get(int(p.sales_order_id or 0)).order_no if packed_sales_by_id.get(int(p.sales_order_id or 0)) else None,
                "order_no": packed_sales_by_id.get(int(p.sales_order_id or 0)).order_no if packed_sales_by_id.get(int(p.sales_order_id or 0)) else None,
                "total_quantity": p.total_quantity,
            }
            for p in packed
        ]
        ready = db.query(Package).filter(Package.status.in_(["received_in_storage", "reserved"])).all()
        ready_so_ids = {int(p.sales_order_id) for p in ready if p.sales_order_id}
        ready_sales_by_id = {
            int(so.id): so
            for so in db.query(SalesOrder).filter(SalesOrder.id.in_(ready_so_ids)).all()
        } if ready_so_ids else {}
        ready_packages = [
            {
                "id": p.id,
                "package_no": p.package_no,
                "sales_order_id": p.sales_order_id,
                "sales_order_no": ready_sales_by_id.get(int(p.sales_order_id or 0)).order_no if ready_sales_by_id.get(int(p.sales_order_id or 0)) else None,
                "order_no": ready_sales_by_id.get(int(p.sales_order_id or 0)).order_no if ready_sales_by_id.get(int(p.sales_order_id or 0)) else None,
                "total_quantity": p.total_quantity,
                "status": p.status,
            }
            for p in ready
        ]
        grouped: dict[int, dict] = {}
        reservation_rows = (
            db.query(
                StockReservation.sales_order_id,
                SalesOrder.order_no,
                SalesOrder.order_type,
                Customer.name.label("customer_name"),
                Customer.address.label("customer_address"),
                Package.id.label("package_id"),
                Package.package_no,
                Package.status.label("package_status"),
                func.coalesce(func.sum(StockReservation.quantity), 0).label("reserved_qty"),
            )
            .join(SalesOrder, SalesOrder.id == StockReservation.sales_order_id)
            .outerjoin(Customer, Customer.id == SalesOrder.customer_id)
            .outerjoin(Package, Package.id == StockReservation.package_id)
            .filter(
                SalesOrder.order_type == "branded_stock_sale",
                SalesOrder.status.in_(["ready", "reserved"]),
            )
            .group_by(
                StockReservation.sales_order_id,
                SalesOrder.order_no,
                SalesOrder.order_type,
                Customer.name,
                Customer.address,
                Package.id,
                Package.package_no,
                Package.status,
            )
            .all()
        )
        for row in reservation_rows:
            so_id = int(row.sales_order_id)
            reserved_qty = int(row.reserved_qty or 0)
            g = grouped.setdefault(
                so_id,
                {
                    "sales_order_id": so_id,
                    "sales_order_no": row.order_no,
                    "order_type": row.order_type,
                    "shipment_type": _shipment_type_label(row.order_type),
                    "customer_name": row.customer_name,
                    "customer_address": row.customer_address,
                    "destination": row.customer_address,
                    "shipment_id": None,
                    "shipment_no": None,
                    "shipment_status": "not_created",
                    "packages": 0,
                    "quantity": 0,
                    "reserved_qty": 0,
                    "pending_qty": 0,
                    "package_lines": [],
                    "_ready_package_ids": set(),
                },
            )
            g["reserved_qty"] += reserved_qty
            package_status = str(row.package_status or "")
            if package_status in ("received_in_storage", "reserved"):
                g["quantity"] += reserved_qty
                if row.package_id is not None:
                    pkg_id = int(row.package_id)
                    if pkg_id not in g["_ready_package_ids"]:
                        g["_ready_package_ids"].add(pkg_id)
                        g["packages"] += 1
                g["package_lines"].append(
                    {
                        "package_id": int(row.package_id) if row.package_id is not None else None,
                        "package_no": row.package_no,
                        "reserved_qty": reserved_qty,
                        "status": package_status,
                    }
                )
            else:
                g["pending_qty"] += reserved_qty
        so_ids = [int(x) for x in grouped.keys()]
        if so_ids:
            shipment_rows = (
                db.query(Shipment)
                .filter(Shipment.sales_order_id.in_(so_ids))
                .order_by(Shipment.sales_order_id.asc(), Shipment.id.desc())
                .all()
            )
            latest_by_so: dict[int, Shipment] = {}
            for sh in shipment_rows:
                sid = int(sh.sales_order_id or 0)
                if sid <= 0 or sid in latest_by_so:
                    continue
                latest_by_so[sid] = sh
            for so_id, row in grouped.items():
                sh = latest_by_so.get(int(so_id))
                if not sh:
                    continue
                row["shipment_id"] = int(sh.id)
                row["shipment_no"] = sh.shipment_no
                row["shipment_status"] = sh.status
        ready_to_ship = [
            {k: v for k, v in g.items() if k != "_ready_package_ids"}
            for g in sorted(grouped.values(), key=lambda x: int(x["sales_order_id"]))
            if int(g.get("quantity") or 0) > 0 or int(g.get("pending_qty") or 0) > 0
        ]

    return {
        "department": {"id": d.id, "code": d.code, "name": d.name},
        "incoming_bundles": [
            {
                "id": b.id,
                "bundle_no": b.bundle_no,
                "production_order_id": b.production_order_id,
                "production_no": bundle_production_no_by_id.get(int(b.production_order_id)),
                "order_no": bundle_order_no_by_id.get(int(b.production_order_id)),
                "sales_order_no": bundle_sales_order_no_by_id.get(int(b.production_order_id)),
                "model_id": b.model_id,
                "color": b.color,
                "size": b.size,
                "quantity": b.quantity,
                "status": b.status,
                "sewing_factory_code": b.sewing_factory_code,
                **_textile_payload(_bundle_textile_code(b) if d.code in _SEWING_LOGISTICS_DEPTS else None),
                **_material_payload_for_po(bundle_material_by_po, int(b.production_order_id or 0)),
                **_production_context_for_po(bundle_production_context_by_po, int(b.production_order_id or 0)),
            }
            for b in incoming_bundles
        ],
        "incoming_bundle_groups": incoming_bundle_groups,
        "incoming_work_orders": incoming_work_orders,
        "replacement_cutting_work": replacement_cutting_work,
        "replacement_sewing_work": replacement_sewing_work,
        "active_work_orders": [
            _work_order_card_payload(w, received_by_po, textile_by_work_order_id.get(int(w.id)), material_by_po, production_context_by_po)
            for w in active
        ],
        "pending_work_orders": [
            _work_order_card_payload(w, received_by_po, textile_by_work_order_id.get(int(w.id)), material_by_po, production_context_by_po)
            for w in pending_work_orders
        ],
        "in_progress_work_orders": [
            _work_order_card_payload(w, received_by_po, textile_by_work_order_id.get(int(w.id)), material_by_po, production_context_by_po)
            for w in in_progress_work_orders
        ],
        "blocked": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "status": w.status,
                "block_reason": w.block_reason,
            }
            for w in blocked
        ],
        "overdue": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "status": w.status,
                "deadline": w.deadline,
            }
            for w in overdue
        ],
        "needs_qc": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "failed_qty": w.failed_qty,
            }
            for w in needs_qc
        ],
        "done_today": [
            {
                **_work_order_card_payload(w, received_by_po, textile_by_work_order_id.get(int(w.id)), material_by_po, production_context_by_po),
                "end_time": w.end_time,
            }
            for w in done_today
        ],
        "awaiting_packaging": awaiting_packaging,
        "pending_packages": pending_packages,
        "ready_packages": ready_packages,
        "ready_to_ship": ready_to_ship,
    }
