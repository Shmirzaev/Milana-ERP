from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import aliased, load_only, selectinload

from app.core.deps import CurrentUser, DbSession, user_permissions
from app.core.dt import as_utc
from app.models import (
    BrandedPlanningOrder,
    Bundle,
    Customer,
    Department,
    Package,
    ProductionOrder,
    ProductionBatch,
    SalesOrder,
    SalesOrderItem,
    Shipment,
    StockReservation,
    SewingRecord,
    SewingReplacementRequest,
    WorkOrder,
    ModelBOM,
    ModelImage,
    Model,
    ProductionOrderItem,
    public_production_order_no,
    Item,
    FinishedGoodsStock,
    StockBatch,
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
    SEWING_FACTORY_ALIASES,
    SEWING_FACTORY_CODES,
    resolve_sewing_factory_code,
)
from app.services.model_images import model_display_image_url
from app.services.factory_scope import require_operational_department_access
from app.services.production import WORK_ORDER_OPERATION_PERMISSIONS

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
_CUTTING_PRODUCTION_STATUSES = ("planning", "cutting")
_REFERENCE_BATCH_SIZE = 400
_DOWNSTREAM_BUNDLE_STATUSES = (
    "sent_to_printing",
    "received_printing",
    "sent_to_sewing",
    "received_sewing",
)


def _require_inbox_department_permission(department: Department, current: CurrentUser) -> None:
    operation = _DEPT_OPERATION.get(department.code)
    required = WORK_ORDER_OPERATION_PERMISSIONS.get(operation or "", set())
    granted = set(user_permissions(current))
    if required and "*" not in granted and not required.intersection(granted):
        raise HTTPException(403, f"Missing permission for {department.code} department inbox")


@router.get("/packages")
def finished_goods_packages(
    db: DbSession,
    current: CurrentUser,
    status: str = Query("ready", pattern="^(pending|ready)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    q: str | None = Query(None, max_length=100),
):
    department = _resolve_department(db, current, "FGS")
    _require_inbox_department_permission(department, current)
    package_statuses = ("packed",) if status == "pending" else ("received_in_storage", "reserved")
    query = (
        db.query(
            Package.id,
            Package.package_no,
            Package.sales_order_id,
            Package.total_quantity,
            Package.status,
            SalesOrder.order_no,
        )
        .outerjoin(SalesOrder, SalesOrder.id == Package.sales_order_id)
        .filter(Package.status.in_(package_statuses))
    )
    term = (q or "").strip()
    if term:
        escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_term}%"
        query = query.filter(
            or_(
                Package.package_no.ilike(pattern, escape="\\"),
                SalesOrder.order_no.ilike(pattern, escape="\\"),
            )
        )
    total = int(query.order_by(None).count())
    group_keys = (
        query.with_entities(Package.sales_order_id)
        .group_by(Package.sales_order_id)
        .order_by(None)
        .subquery()
    )
    group_total = int(db.query(func.count()).select_from(group_keys).scalar() or 0)
    rows = query.order_by(Package.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": [
            {
                "id": int(row.id),
                "package_no": row.package_no,
                "sales_order_id": int(row.sales_order_id) if row.sales_order_id is not None else None,
                "sales_order_no": row.order_no,
                "order_no": row.order_no,
                "total_quantity": int(row.total_quantity or 0),
                "status": row.status,
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "group_total": group_total,
        "has_more": page * page_size < total,
    }


def _awaiting_packaging_query(db, packaging_dept_id: int):
    sewing = (
        db.query(
            WorkOrder.production_order_id.label("production_order_id"),
            WorkOrder.production_batch_id.label("production_batch_id"),
            func.sum(func.coalesce(WorkOrder.passed_qty, 0)).label("sewn_passed"),
        )
        .filter(WorkOrder.operation == "sewing")
        .group_by(WorkOrder.production_order_id, WorkOrder.production_batch_id)
        .subquery()
    )
    packaging = (
        db.query(
            WorkOrder.production_order_id.label("production_order_id"),
            WorkOrder.production_batch_id.label("production_batch_id"),
            func.sum(func.coalesce(WorkOrder.passed_qty, 0)).label("already_packed"),
        )
        .filter(
            WorkOrder.operation == "packaging",
            WorkOrder.department_id == packaging_dept_id,
        )
        .group_by(WorkOrder.production_order_id, WorkOrder.production_batch_id)
        .subquery()
    )
    same_batch = or_(
        sewing.c.production_batch_id == packaging.c.production_batch_id,
        (sewing.c.production_batch_id.is_(None) & packaging.c.production_batch_id.is_(None)),
    )
    query = (
        db.query(
            sewing.c.production_order_id.label("production_order_id"),
            sewing.c.production_batch_id.label("production_batch_id"),
            sewing.c.sewn_passed,
            packaging.c.already_packed,
        )
        .join(
            ProductionOrder,
            ProductionOrder.id == sewing.c.production_order_id,
        )
        .join(
            packaging,
            (packaging.c.production_order_id == sewing.c.production_order_id)
            & same_batch
        )
        .filter(
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            sewing.c.sewn_passed > packaging.c.already_packed,
        )
    )
    return query, sewing


def _awaiting_packaging_rows(
    db,
    packaging_dept_id: int,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> tuple[list[dict], int]:
    query, sewing = _awaiting_packaging_query(db, packaging_dept_id)
    total = int(query.order_by(None).count())
    query = query.order_by(
        sewing.c.production_order_id.asc(),
        sewing.c.production_batch_id.asc().nullsfirst(),
    )
    if limit is not None:
        query = query.offset(offset).limit(limit)
    pairs = [
        {
            "production_order_id": int(row.production_order_id),
            "production_batch_id": int(row.production_batch_id) if row.production_batch_id is not None else None,
            "sewn_passed": int(row.sewn_passed or 0),
            "already_packed": int(row.already_packed or 0),
        }
        for row in query.all()
    ]
    if not pairs:
        return [], total

    po_ids = sorted({row["production_order_id"] for row in pairs})
    batch_ids = sorted({row["production_batch_id"] for row in pairs if row["production_batch_id"] is not None})
    context_by_po = _production_context_by_production_order(db, po_ids)
    production_by_id = {
        int(row.id): row
        for row in db.query(
            ProductionOrder.id,
            ProductionOrder.production_no,
            ProductionOrder.sales_order_id,
        ).filter(ProductionOrder.id.in_(po_ids)).all()
    }
    sales_order_ids = sorted({int(row.sales_order_id) for row in production_by_id.values() if row.sales_order_id})
    sales_no_by_id = {
        int(row.id): row.order_no
        for row in db.query(SalesOrder.id, SalesOrder.order_no).filter(SalesOrder.id.in_(sales_order_ids)).all()
    } if sales_order_ids else {}
    batches_by_id = {
        int(batch.id): batch
        for batch in (
            db.query(ProductionBatch.id, ProductionBatch.batch_no, ProductionBatch.name)
            .filter(ProductionBatch.id.in_(batch_ids))
            .all()
            if batch_ids
            else []
        )
    }
    for row in pairs:
        context = _production_context_for_po(context_by_po, row["production_order_id"])
        production = production_by_id.get(row["production_order_id"])
        batch = batches_by_id.get(row["production_batch_id"])
        row["batch_no"] = batch.batch_no if batch else None
        row["batch_name"] = batch.name if batch else None
        row["ready_qty"] = row["sewn_passed"] - row["already_packed"]
        row.update(context)
        row["production_no"] = production.production_no if production else None
        sales_order_no = sales_no_by_id.get(int(production.sales_order_id)) if production and production.sales_order_id else None
        row["order_no"] = (
            sales_order_no
            or (public_production_order_no(production.production_no) if production else None)
            or (production.production_no if production else None)
        )
        row["sales_order_no"] = sales_order_no
    return pairs, total


@router.get("/awaiting-packaging")
def awaiting_packaging_page(
    db: DbSession,
    current: CurrentUser,
    dept: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    department = _resolve_department(db, current, dept)
    if department.code not in {"PKG", DEPT_BESTTEX_PACKAGING, DEPT_ECO_COTTON_PACKAGING}:
        raise HTTPException(404, "Awaiting packaging queue not found")
    _require_inbox_department_permission(department, current)
    offset = (page - 1) * page_size
    rows, total = _awaiting_packaging_rows(
        db,
        int(department.id),
        offset=offset,
        limit=page_size,
    )
    return {
        "rows": rows,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }


def _orders_progressed_beyond_cutting(db: DbSession, production_order_ids: list[int]) -> set[int]:
    ids = sorted({int(value) for value in production_order_ids if value})
    if not ids:
        return set()

    progressed = {
        int(value)
        for (value,) in db.query(ProductionOrder.id).filter(
            ProductionOrder.id.in_(ids),
            ProductionOrder.status.notin_(_CUTTING_PRODUCTION_STATUSES),
        ).all()
    }
    progressed.update(
        int(value)
        for (value,) in db.query(WorkOrder.production_order_id).filter(
            WorkOrder.production_order_id.in_(ids),
            WorkOrder.operation != "cutting",
            or_(
                WorkOrder.status.in_(("in_progress", "completed")),
                WorkOrder.start_time.isnot(None),
                WorkOrder.end_time.isnot(None),
                WorkOrder.actual_input_qty > 0,
                WorkOrder.actual_output_qty > 0,
                WorkOrder.passed_qty > 0,
                WorkOrder.failed_qty > 0,
                WorkOrder.rework_qty > 0,
            ),
        ).distinct().all()
    )
    progressed.update(
        int(value)
        for (value,) in db.query(Bundle.production_order_id).filter(
            Bundle.production_order_id.in_(ids),
            Bundle.status.in_(_DOWNSTREAM_BUNDLE_STATUSES),
        ).distinct().all()
    )
    progressed.update(
        int(value)
        for (value,) in db.query(Package.production_order_id).filter(
            Package.production_order_id.in_(ids),
        ).distinct().all()
        if value is not None
    )
    progressed.update(
        int(value)
        for (value,) in db.query(FinishedGoodsStock.production_order_id).filter(
            FinishedGoodsStock.production_order_id.in_(ids),
        ).distinct().all()
        if value is not None
    )
    return progressed


def _open_usluga_cutting_order_ids(db: DbSession, production_order_ids: list[int]) -> set[int]:
    ids = sorted({int(value) for value in production_order_ids if value})
    if not ids:
        return set()

    return {
        int(value)
        for (value,) in (
            db.query(WorkOrder.production_order_id)
            .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
            .filter(
                WorkOrder.production_order_id.in_(ids),
                WorkOrder.operation == "cutting",
                WorkOrder.status.notin_(("completed", "rejected", "cancelled")),
                ProductionOrder.source_type == "usluga",
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .distinct()
            .all()
        )
    }


def _shipment_type_label(order_type: str | None) -> str:
    mapping = {
        "branded_stock_sale": "from_stock",
        "client_order": "client_order",
    }
    return mapping.get(str(order_type or "").strip(), "standard")


def _resolve_department(db: DbSession, current: CurrentUser, dept: str | None) -> Department:
    if dept:
        found = db.query(Department).options(
            load_only(Department.id, Department.code),
        ).filter(Department.code == dept.upper()).first()
        if not found:
            raise HTTPException(404, f"Department {dept} not found")
        require_operational_department_access(current, found.code)
        return found
    if not current.department_id:
        raise HTTPException(400, "User has no department; pass ?dept=CODE")
    found = db.get(Department, current.department_id)
    if not found:
        raise HTTPException(404, "User department not found")
    require_operational_department_access(current, found.code)
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
    *,
    work_order_ids: set[int] | None = None,
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
    if work_order_ids is not None:
        if not work_order_ids:
            return []
        qry = qry.filter(WorkOrder.id.in_(sorted(work_order_ids)))
    target_rows = qry.order_by(WorkOrder.id.desc())
    if work_order_ids is None:
        target_rows = target_rows.limit(500)
    target_rows = target_rows.all()
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
    incoming.sort(key=lambda row: (0 if int(row["ready_qty"] or 0) > 0 else 1, -int(row["work_order_id"])))
    return incoming[:200] if work_order_ids is None else incoming


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


def _core_inbox_identity_key(row: dict) -> str:
    work_order_id = row.get("work_order_id") or row.get("id")
    if work_order_id:
        return f"wo-{int(work_order_id)}"
    operation = row.get("target_operation") or row.get("operation") or "sewing"
    textile_code = row.get("textile_code") or "all"
    return f"po-{int(row['production_order_id'])}-{operation}-{textile_code}"


def _ids_in_chunks(values: set[int]):
    ordered = sorted(values)
    for start in range(0, len(ordered), _REFERENCE_BATCH_SIZE):
        yield ordered[start:start + _REFERENCE_BATCH_SIZE]


def _core_inbox_identity_sources(
    db: DbSession,
    department: Department,
    inbox_department_ids: list[int],
    textile_filter: str | None,
    *,
    now: datetime,
    client_tz,
) -> list[dict]:
    """Discover all eligible canonical identities without hydrating card data.

    This intentionally omits the legacy queue caps. It records each source row
    in merge order so page hydration can retain both Map insertion order and
    the later-source-wins field semantics used by DepartmentOrderList.
    """
    department_code = str(department.code)
    sources: list[dict] = []

    # Incoming work order candidates retain the predecessor and quantity checks
    # used by _incoming_work_items, followed by its ready-first/id-desc order.
    incoming_po_ids: set[int] = set()
    incoming_work_rows: list[WorkOrder] = []
    incoming_work_textile: dict[int, str | None] = {}
    target_operation = _DEPT_OPERATION.get(department_code)
    eligible_incoming_work_po_ids: set[int] = set()
    if target_operation:
        incoming_query = (
            db.query(WorkOrder)
            .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
            .filter(
                WorkOrder.operation == target_operation,
                WorkOrder.status.notin_(("completed", "rejected", "cancelled")),
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
        )
        if inbox_department_ids:
            incoming_query = incoming_query.filter(WorkOrder.department_id.in_(inbox_department_ids))
        incoming_work_rows = incoming_query.order_by(WorkOrder.id.desc()).all()
        incoming_work_textile = _textile_codes_for_work_orders(db, incoming_work_rows)
        if textile_filter:
            incoming_work_rows = [
                row for row in incoming_work_rows
                if incoming_work_textile.get(int(row.id)) == textile_filter
            ]
        incoming_po_ids = {
            int(row.production_order_id)
            for row in incoming_work_rows
            if row.production_order_id
        }
        by_po: dict[int, dict[str, WorkOrder]] = {}
        for ids in _ids_in_chunks(incoming_po_ids):
            for row in db.query(WorkOrder).filter(WorkOrder.production_order_id.in_(ids)).all():
                by_po.setdefault(int(row.production_order_id), {})[str(row.operation)] = row
        incoming_rows: list[tuple[WorkOrder, int]] = []
        for target in incoming_work_rows:
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
            po_id = int(target.production_order_id)
            eligible_incoming_work_po_ids.add(po_id)
            incoming_rows.append((target, ready_qty))
        incoming_rows.sort(key=lambda item: (0 if item[1] > 0 else 1, -int(item[0].id)))
        for target, ready_qty in incoming_rows:
            identity_row = {
                "work_order_id": int(target.id),
                "production_order_id": int(target.production_order_id),
                "target_operation": target.operation,
                "textile_code": (
                    incoming_work_textile.get(int(target.id))
                    if target_operation == "sewing" else None
                ),
            }
            sources.append({
                "key": _core_inbox_identity_key(identity_row),
                "queue_kind": "incoming",
                "descriptor": {"source": "incoming_work", "work_order_id": int(target.id)},
                "sort": (0 if ready_qty > 0 else 1, -int(target.id)),
            })

    # Bundle groups are suppressed globally by PO when at least one valid
    # incoming-work row exists, matching the frontend's PO-wide suppression.
    incoming_bundle_statuses = ["sent_to_printing", "sent_to_sewing"]
    if department_code in _SEWING_LOGISTICS_DEPTS:
        incoming_bundle_statuses.append("created")
    bundle_rows = (
        db.query(
            Bundle,
            func.coalesce(func.nullif(SalesOrder.order_no, ""), ProductionOrder.production_no).label("order_no"),
            ProductionOrder.production_no,
        )
        .join(ProductionOrder, ProductionOrder.id == Bundle.production_order_id)
        .outerjoin(SalesOrder, SalesOrder.id == ProductionOrder.sales_order_id)
        .filter(
            Bundle.next_department_id.in_(inbox_department_ids),
            Bundle.status.in_(incoming_bundle_statuses),
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
        .order_by(Bundle.id.desc())
        .all()
    )
    if textile_filter:
        bundle_rows = [row for row in bundle_rows if _bundle_textile_code(row[0]) == textile_filter]
    bundle_po_ids = {int(bundle.production_order_id) for bundle, _, _ in bundle_rows}
    bundle_work_by_po: dict[int, dict[str, WorkOrder]] = {}
    for ids in _ids_in_chunks(bundle_po_ids):
        for row in db.query(WorkOrder).filter(WorkOrder.production_order_id.in_(ids)).all():
            bundle_work_by_po.setdefault(int(row.production_order_id), {})[str(row.operation)] = row
    grouped_bundles: dict[tuple[int, str], dict] = {}
    for bundle, order_no, production_no in bundle_rows:
        po_id = int(bundle.production_order_id)
        textile_code = _bundle_textile_code(bundle)
        group = grouped_bundles.setdefault((po_id, textile_code), {
            "po_id": po_id,
            "textile_code": textile_code,
            "order_no": order_no,
            "production_no": production_no,
            "ready_qty": 0,
            "sewing_work_order_id": (
                int(bundle_work_by_po[po_id]["sewing"].id)
                if "sewing" in bundle_work_by_po.get(po_id, {}) else None
            ),
        })
        group["ready_qty"] += int(bundle.quantity or 0)
    grouped_rows = sorted(
        grouped_bundles.values(),
        key=lambda row: (
            -int(row["ready_qty"] or 0),
            str(row.get("order_no") or row.get("production_no") or ""),
            -int(row["po_id"]),
        ),
    )
    for group in grouped_rows:
        if int(group["po_id"]) in eligible_incoming_work_po_ids:
            continue
        identity_row = {
            "work_order_id": group["sewing_work_order_id"],
            "production_order_id": group["po_id"],
            "target_operation": "sewing",
            "textile_code": group["textile_code"],
        }
        sources.append({
            "key": _core_inbox_identity_key(identity_row),
            "queue_kind": "incoming",
            "descriptor": {
                "source": "incoming_bundle_group",
                "production_order_id": int(group["po_id"]),
                "textile_code": group["textile_code"],
            },
            "sort": (
                -int(group["ready_qty"] or 0),
                str(group.get("order_no") or group.get("production_no") or ""),
                -int(group["po_id"]),
            ),
        })

    # Active/completed candidates use the same department and factory filters
    # as the legacy work_orders list, but without its 500-row fetch ceiling.
    work_query = (
        db.query(WorkOrder)
        .join(ProductionOrder, ProductionOrder.id == WorkOrder.production_order_id)
        .filter(ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES))
    )
    if department_code in _SEWING_LOGISTICS_DEPTS:
        work_query = work_query.filter(
            WorkOrder.operation == "sewing",
            WorkOrder.department_id.in_(inbox_department_ids),
        )
    else:
        work_query = work_query.filter(WorkOrder.department_id == int(department.id))
    work_orders = work_query.order_by(WorkOrder.id.desc()).all()
    textile_by_work_order_id = _textile_codes_for_work_orders(db, work_orders)
    if textile_filter:
        work_orders = [
            row for row in work_orders
            if textile_by_work_order_id.get(int(row.id)) == textile_filter
        ]

    replacement_work_order_ids: set[int] = set()
    if department_code in {"CUT", DEPT_ECO_COTTON_CUTTING}:
        replacement_query = (
            db.query(SewingReplacementRequest.cutting_work_order_id)
            .join(WorkOrder, WorkOrder.id == SewingReplacementRequest.cutting_work_order_id)
            .join(ProductionOrder, ProductionOrder.id == SewingReplacementRequest.production_order_id)
            .filter(
                WorkOrder.department_id == int(department.id),
                SewingReplacementRequest.status == "waiting_cutting",
                SewingReplacementRequest.cut_qty < SewingReplacementRequest.requested_qty,
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .distinct()
        )
        replacement_work_order_ids = {
            int(value) for (value,) in replacement_query.all() if value is not None
        }

    progressed_order_ids: set[int] = set()
    if department_code in {"CUT", DEPT_ECO_COTTON_CUTTING}:
        scoped_po_ids = {int(row.production_order_id) for row in work_orders if row.production_order_id}
        for ids in _ids_in_chunks(scoped_po_ids):
            progressed_order_ids.update(_orders_progressed_beyond_cutting(db, ids))
        if department_code == DEPT_ECO_COTTON_CUTTING:
            for ids in _ids_in_chunks(scoped_po_ids):
                progressed_order_ids.difference_update(_open_usluga_cutting_order_ids(db, ids))

    today_client = now.astimezone(client_tz).date()
    for work_order in work_orders:
        status = str(work_order.status or "")
        po_id = int(work_order.production_order_id or 0)
        if status in _PENDING_WO_STATUSES:
            if (
                department_code in {"CUT", DEPT_ECO_COTTON_CUTTING}
                and po_id in progressed_order_ids
            ) or int(work_order.id) in replacement_work_order_ids:
                continue
            queue_kind = "pending"
        elif status in _IN_PROGRESS_WO_STATUSES:
            if (
                department_code in {"CUT", DEPT_ECO_COTTON_CUTTING}
                and po_id in progressed_order_ids
            ) or int(work_order.id) in replacement_work_order_ids:
                continue
            queue_kind = "in_progress"
        elif (
            status == "completed"
            and work_order.end_time
            and as_utc(work_order.end_time)
            and as_utc(work_order.end_time).astimezone(client_tz).date() == today_client
        ):
            queue_kind = "completed"
        else:
            continue
        identity_row = {
            "id": int(work_order.id),
            "production_order_id": po_id,
            "operation": work_order.operation,
            "textile_code": textile_by_work_order_id.get(int(work_order.id)),
        }
        sources.append({
            "key": _core_inbox_identity_key(identity_row),
            "queue_kind": queue_kind,
            "descriptor": {
                "source": "work_order",
                "work_order_id": int(work_order.id),
                "queue_kind": queue_kind,
            },
            "sort": -int(work_order.id),
        })

    # A Python dict preserves the first insertion position while appending each
    # later contributing row so the final page can reproduce spread semantics.
    merged: dict[str, dict] = {}
    incoming_work_sources = [row for row in sources if row["descriptor"]["source"] == "incoming_work"]
    incoming_bundle_sources = [row for row in sources if row["descriptor"]["source"] == "incoming_bundle_group"]
    incoming_work_sources.sort(key=lambda row: row["sort"])
    incoming_bundle_sources.sort(key=lambda row: row["sort"])
    ordered_sources = incoming_work_sources + incoming_bundle_sources
    for queue_kind in ("pending", "in_progress", "completed"):
        queue_sources = [row for row in sources if row["queue_kind"] == queue_kind]
        queue_sources.sort(key=lambda row: row["sort"], reverse=True)
        ordered_sources.extend(queue_sources)
    for source in ordered_sources:
        entry = merged.setdefault(source["key"], {"key": source["key"], "sources": []})
        entry["sources"].append(source["descriptor"])
        entry["queue_kind"] = source["queue_kind"]
    return list(merged.values())


def _hydrate_core_inbox_page(
    db: DbSession,
    page: list[dict],
    dept_code: str,
    inbox_department_ids: list[int],
    textile_filter: str | None,
) -> list[dict]:
    incoming_work_ids = {
        int(source["work_order_id"])
        for entry in page for source in entry["sources"]
        if source["source"] == "incoming_work"
    }
    bundle_groups = {
        (int(source["production_order_id"]), str(source["textile_code"]))
        for entry in page for source in entry["sources"]
        if source["source"] == "incoming_bundle_group"
    }
    work_order_ids = {
        int(source["work_order_id"])
        for entry in page for source in entry["sources"]
        if source["source"] == "work_order"
    }

    hydrated: dict[tuple, dict] = {}
    for row in _incoming_work_items(
        db,
        dept_code,
        inbox_department_ids,
        textile_filter,
        work_order_ids=incoming_work_ids,
    ):
        hydrated[("incoming_work", int(row["work_order_id"]))] = row

    if bundle_groups:
        bundle_po_ids = {po_id for po_id, _textile in bundle_groups}
        bundle_statuses = ["sent_to_printing", "sent_to_sewing"]
        if dept_code in _SEWING_LOGISTICS_DEPTS:
            bundle_statuses.append("created")
        matching_bundles = (
            db.query(Bundle)
            .join(ProductionOrder, ProductionOrder.id == Bundle.production_order_id)
            .filter(
                Bundle.production_order_id.in_(sorted(bundle_po_ids)),
                Bundle.next_department_id.in_(inbox_department_ids),
                Bundle.status.in_(bundle_statuses),
                ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
            )
            .order_by(Bundle.id.desc())
            .all()
        )
        matching_bundles = [
            bundle for bundle in matching_bundles
            if (int(bundle.production_order_id), _bundle_textile_code(bundle)) in bundle_groups
        ]
        for row in _incoming_bundle_groups(db, matching_bundles):
            hydrated[("incoming_bundle_group", int(row["production_order_id"]), str(row["textile_code"]))] = row

    work_orders: list[WorkOrder] = []
    if work_order_ids:
        work_orders = (
            db.query(WorkOrder)
            .filter(WorkOrder.id.in_(sorted(work_order_ids)))
            .order_by(WorkOrder.id.desc())
            .all()
        )
    textile_by_work_order_id = _textile_codes_for_work_orders(db, work_orders)
    work_order_po_ids = [int(row.production_order_id) for row in work_orders if row.production_order_id]
    received_by_po = _received_bundle_totals_by_po(db, work_order_po_ids)
    material_by_po = _material_payload_by_production_order(db, work_order_po_ids)
    production_context_by_po = _production_context_by_production_order(db, work_order_po_ids)
    work_order_by_id = {int(row.id): row for row in work_orders}
    for source in (
        source
        for entry in page for source in entry["sources"]
        if source["source"] == "work_order"
    ):
        work_order_id = int(source["work_order_id"])
        work_order = work_order_by_id.get(work_order_id)
        if not work_order:
            continue
        row = _work_order_card_payload(
            work_order,
            received_by_po,
            textile_by_work_order_id.get(work_order_id),
            material_by_po,
            production_context_by_po,
        )
        if source["queue_kind"] == "completed":
            row["end_time"] = work_order.end_time
        hydrated[("work_order", work_order_id)] = row

    output: list[dict] = []
    for entry in page:
        merged_row: dict = {}
        for source in entry["sources"]:
            key = (source["source"], int(source["work_order_id"])) if source["source"] in {"incoming_work", "work_order"} else (
                source["source"],
                int(source["production_order_id"]),
                str(source["textile_code"]),
            )
            payload = hydrated.get(key)
            if payload:
                merged_row.update(payload)
        merged_row["queue_kind"] = entry["queue_kind"]
        output.append(merged_row)
    return output


@router.get("/department-orders")
def department_order_page(
    db: DbSession,
    current: CurrentUser,
    dept: str | None = None,
    tz: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Return a bounded page of canonical DepartmentOrderList identities.

    The legacy /api/inbox response remains unchanged. This opt-in route counts
    the complete eligible merged identity set before it hydrates only the rows
    needed for the requested page.
    """
    department = _resolve_department(db, current, dept)
    _require_inbox_department_permission(department, current)
    now = datetime.now(timezone.utc)
    try:
        client_tz = ZoneInfo(tz) if tz else timezone.utc
    except Exception:
        client_tz = timezone.utc

    textile_filter = (
        department.code
        if department.code in {DEPT_MILANA, DEPT_BESTTEX, DEPT_ECO_COTTON}
        else None
    )
    sewing_department_ids = _sewing_work_order_department_ids(db)
    if department.code in _SEWING_LOGISTICS_DEPTS and not sewing_department_ids:
        sewing_department_ids = [int(department.id)]
    inbox_department_ids = (
        sewing_department_ids
        if department.code in _SEWING_LOGISTICS_DEPTS
        else [int(department.id)]
    )
    identities = _core_inbox_identity_sources(
        db,
        department,
        inbox_department_ids,
        textile_filter,
        now=now,
        client_tz=client_tz,
    )
    total = len(identities)
    page = identities[offset:offset + limit]
    rows = _hydrate_core_inbox_page(
        db,
        page,
        department.code,
        inbox_department_ids,
        textile_filter,
    )
    return {
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


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


def _reference_id_chunks(values: set[int]):
    ordered = sorted(values)
    for start in range(0, len(ordered), _REFERENCE_BATCH_SIZE):
        yield ordered[start:start + _REFERENCE_BATCH_SIZE]


def _bom_material_image_url(
    bom_photo_url: str | None,
    stock_batch_id: int | None,
    item_image_url: str | None,
    stock_batch_images: dict[int, str | None],
) -> str | None:
    return (
        bom_photo_url
        or stock_batch_images.get(int(stock_batch_id or 0))
        or item_image_url
    )


def _material_payload_by_production_order(db: DbSession, production_order_ids: list[int]) -> dict[int, dict]:
    po_ids = sorted({int(po_id) for po_id in production_order_ids if po_id})
    if not po_ids:
        return {}
    po_rows = []
    for ids in _reference_id_chunks(set(po_ids)):
        po_rows.extend(
            db.query(ProductionOrder.id, ProductionOrder.model_id)
            .filter(ProductionOrder.id.in_(ids))
            .all()
        )
    model_by_po = {int(po_id): int(model_id) for po_id, model_id in po_rows if model_id}
    model_ids = sorted(set(model_by_po.values()))
    if not model_ids:
        return {}

    by_model: dict[int, dict] = {}
    bom_rows = []
    for ids in _reference_id_chunks(set(model_ids)):
        bom_rows.extend(
            db.query(
                ModelBOM.id,
                ModelBOM.model_id,
                ModelBOM.stock_batch_id,
                ModelBOM.photo_url,
                Item.id.label("item_id"),
                Item.sku.label("item_sku"),
                Item.name.label("item_name"),
                Item.image_url.label("item_image_url"),
            )
            .join(Item, Item.id == ModelBOM.item_id)
            .filter(ModelBOM.model_id.in_(ids), Item.category.in_(_MATERIAL_CATEGORIES))
            .order_by(ModelBOM.id.asc())
            .all()
        )
    stock_batch_images: dict[int, str | None] = {}
    stock_batch_ids = {int(row.stock_batch_id) for row in bom_rows if row.stock_batch_id}
    for ids in _reference_id_chunks(stock_batch_ids):
        stock_batch_images.update({
            int(batch_id): image_url
            for batch_id, image_url in db.query(StockBatch.id, StockBatch.image_url)
            .filter(StockBatch.id.in_(ids))
            .all()
        })

    for bom in bom_rows:
        image_url = _bom_material_image_url(
            bom.photo_url,
            bom.stock_batch_id,
            bom.item_image_url,
            stock_batch_images,
        )
        payload = {
            "material_item_id": int(bom.item_id),
            "material_item_sku": bom.item_sku,
            "material_item_name": bom.item_name,
            "material_image_url": image_url,
        }
        existing = by_model.get(int(bom.model_id))
        if not existing or (not existing.get("material_image_url") and image_url):
            by_model[int(bom.model_id)] = payload

    material_images = []
    for ids in _reference_id_chunks(set(model_ids)):
        material_images.extend(
            db.query(ModelImage.model_id, ModelImage.file_url)
            .filter(
                ModelImage.model_id.in_(ids),
                func.lower(func.coalesce(ModelImage.image_type, "")) == "material",
            )
            .order_by(ModelImage.id.desc())
            .all()
        )
    material_image_models: set[int] = set()
    for model_id_value, file_url in material_images:
        model_id = int(model_id_value)
        if model_id in material_image_models:
            continue
        payload = by_model.setdefault(model_id, _empty_material_payload())
        payload["material_image_url"] = file_url
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
        "planning_order_id": None,
        "planning_order_no": None,
        "planning_order_name": None,
        "production_type": None,
        "sewing_factory_code": None,
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

    po_rows = (
        db.query(
            ProductionOrder.id,
            ProductionOrder.model_id,
            ProductionOrder.planning_order_id,
            ProductionOrder.production_type,
        )
        .filter(ProductionOrder.id.in_(po_ids))
        .all()
    )
    model_by_po = {int(po_id): int(model_id) for po_id, model_id, _, _ in po_rows if model_id}
    planning_order_id_by_po = {
        int(po_id): int(planning_order_id)
        for po_id, _, planning_order_id, _ in po_rows
        if planning_order_id
    }
    production_type_by_po = {
        int(po_id): str(production_type or "") or None
        for po_id, _, _, production_type in po_rows
    }
    planning_order_ids = sorted(set(planning_order_id_by_po.values()))
    planning_order_by_id = {
        int(row.id): row
        for row in (
            db.query(BrandedPlanningOrder)
            .filter(BrandedPlanningOrder.id.in_(planning_order_ids))
            .all()
            if planning_order_ids
            else []
        )
    }
    model_ids = sorted(set(model_by_po.values()))
    model_by_id = {
        int(model.id): model
        for model in (
            db.query(Model)
            .options(
                load_only(Model.id, Model.code, Model.name, Model.details_json),
                selectinload(Model.images).load_only(
                    ModelImage.id,
                    ModelImage.model_id,
                    ModelImage.file_url,
                    ModelImage.file_name,
                    ModelImage.content_type,
                    ModelImage.image_type,
                    ModelImage.is_primary,
                ),
                selectinload(Model.bom).load_only(
                    ModelBOM.id,
                    ModelBOM.model_id,
                    ModelBOM.item_id,
                    ModelBOM.stock_batch_id,
                    ModelBOM.photo_url,
                ),
                selectinload(Model.bom)
                .joinedload(ModelBOM.item)
                .load_only(Item.id, Item.category, Item.image_url),
                selectinload(Model.bom)
                .joinedload(ModelBOM.stock_batch)
                .load_only(StockBatch.id, StockBatch.image_url),
            )
            .filter(Model.id.in_(model_ids))
            .all()
        )
    } if model_ids else {}

    sizes_by_po: dict[int, list[str]] = {}
    sewing_factory_by_po: dict[int, str] = {}
    sewing_rows = (
        db.query(WorkOrder.production_order_id, Department.code)
        .join(Department, Department.id == WorkOrder.department_id)
        .filter(WorkOrder.production_order_id.in_(po_ids), WorkOrder.operation == "sewing")
        .order_by(WorkOrder.id.asc())
        .all()
    )
    for po_id, department_code in sewing_rows:
        sewing_factory_by_po.setdefault(int(po_id), resolve_sewing_factory_code(department_code))

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
        planning_order_id = planning_order_id_by_po.get(po_id)
        planning_order = planning_order_by_id.get(planning_order_id or 0)
        model_no, variant_no = _model_code_parts(model)
        sizes = list(dict.fromkeys(sizes_by_po.get(po_id, [])))
        size_summary, size_count = _size_summary_from_values(sizes)
        out[po_id] = {
            "planning_order_id": planning_order_id,
            "planning_order_no": planning_order.order_no if planning_order else None,
            "planning_order_name": planning_order.ordered_for_name if planning_order else None,
            "production_type": production_type_by_po.get(po_id),
            "sewing_factory_code": sewing_factory_by_po.get(po_id),
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
    received = received_by_po.get(int(w.production_order_id), {}) if w.operation in {"cutting", "sewing"} else {}
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
    limit: int | None = None,
    offset: int = 0,
    suppression_work_order_ids: set[int] | None = None,
) -> tuple[list[dict], int, set[int]]:
    query = (
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
    )
    if limit is None:
        rows = query.all()
        total = len(rows)
        replacement_work_order_ids = {
            int(cutting_work_order.id)
            for _, cutting_work_order, _, _ in rows
        }
    else:
        total = int(query.order_by(None).with_entities(func.count(SewingReplacementRequest.id)).scalar() or 0)
        rows = query.offset(offset).limit(limit).all()
        suppression_query = query.order_by(None).with_entities(
            SewingReplacementRequest.cutting_work_order_id
        ).distinct()
        if suppression_work_order_ids is not None:
            if not suppression_work_order_ids:
                replacement_work_order_ids = set()
            else:
                suppression_query = suppression_query.filter(
                    SewingReplacementRequest.cutting_work_order_id.in_(suppression_work_order_ids)
                )
                replacement_work_order_ids = {
                    int(row[0]) for row in suppression_query.all() if row[0] is not None
                }
        else:
            replacement_work_order_ids = {
                int(row[0])
                for row in suppression_query.all()
                if row[0] is not None
            }
    if not rows:
        return [], total, replacement_work_order_ids

    production_order_ids = sorted({int(request.production_order_id) for request, _, _, _ in rows})
    material_by_po = _material_payload_by_production_order(db, production_order_ids)
    production_context_by_po = _production_context_by_production_order(db, production_order_ids)

    payload = [
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
    return payload, total, replacement_work_order_ids


def _replacement_sewing_work_payload(
    db: DbSession,
    department_ids: list[int],
    textile_filter: str | None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if not department_ids:
        return [], 0
    query = (
        db.query(SewingReplacementRequest, WorkOrder, ProductionOrder)
        .join(WorkOrder, WorkOrder.id == SewingReplacementRequest.sewing_work_order_id)
        .join(ProductionOrder, ProductionOrder.id == SewingReplacementRequest.production_order_id)
        .filter(
            WorkOrder.department_id.in_(department_ids),
            SewingReplacementRequest.status == "waiting_sewing",
            SewingReplacementRequest.replaced_qty < SewingReplacementRequest.cut_qty,
            ProductionOrder.status.notin_(_CANCELLED_PRODUCTION_STATUSES),
        )
    )
    if department_ids:
        query = query.filter(WorkOrder.department_id.in_(department_ids))
    if textile_filter:
        query = query.join(Department, Department.id == WorkOrder.department_id).filter(
            WorkOrder.operation == "sewing"
        )
        aliases_by_code = {
            code: tuple(alias for alias, resolved in SEWING_FACTORY_ALIASES.items() if resolved == code)
            for code in SEWING_FACTORY_CODES
        }

        def resolved_bundle_code(bundle):
            normalized = func.upper(func.trim(func.coalesce(bundle.sewing_factory_code, "")))
            return case(
                *((normalized.in_(aliases), code) for code, aliases in aliases_by_code.items()),
                else_=DEPT_MILANA,
            )

        batch_bundle = aliased(Bundle)
        order_bundle = aliased(Bundle)
        batch_scope = and_(
            batch_bundle.production_order_id == WorkOrder.production_order_id,
            batch_bundle.production_batch_id == WorkOrder.production_batch_id,
        )
        order_scope = order_bundle.production_order_id == WorkOrder.production_order_id
        has_batch_scope = WorkOrder.production_batch_id.is_not(None) & exists().where(batch_scope)
        has_order_scope = exists().where(order_scope)
        batch_other_code = exists().where(
            batch_scope & (resolved_bundle_code(batch_bundle) != textile_filter)
        )
        order_other_code = exists().where(
            order_scope & (resolved_bundle_code(order_bundle) != textile_filter)
        )
        department_fallback = case(
            (Department.code.in_(SEWING_FACTORY_CODES), Department.code),
            else_=DEPT_MILANA,
        )
        query = query.filter(
            (
                WorkOrder.production_batch_id.is_not(None)
                & has_batch_scope
                & ~batch_other_code
            )
            | (~has_batch_scope & has_order_scope & ~order_other_code)
            | (~has_batch_scope & ~has_order_scope & (department_fallback == textile_filter))
        )

    query = query.order_by(SewingReplacementRequest.created_at.asc(), SewingReplacementRequest.id.asc())
    if limit is None:
        rows = query.all()
        total = len(rows)
    else:
        total = int(
            query.order_by(None)
            .with_entities(func.count(SewingReplacementRequest.id))
            .scalar()
            or 0
        )
        query = query.offset(offset).limit(limit)
        rows = query.all()
    if not rows:
        return [], total

    sewing_work_orders = [sewing_work_order for _, sewing_work_order, _ in rows]
    textile_by_work_order_id = _textile_codes_for_work_orders(db, sewing_work_orders)

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
    ], total


@router.get("/replacement-sewing")
def replacement_sewing_page(
    db: DbSession,
    current: CurrentUser,
    dept: Annotated[str, Query()],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    department = _resolve_department(db, current, dept)
    if department.code not in _SEWING_LOGISTICS_DEPTS:
        raise HTTPException(404, "Replacement sewing queue not found")
    _require_inbox_department_permission(department, current)
    department_ids = _sewing_work_order_department_ids(db) or [int(department.id)]
    textile_filter = department.code if department.code in SEWING_FACTORY_CODES else None
    rows, total = _replacement_sewing_work_payload(
        db, department_ids, textile_filter, limit=limit, offset=offset,
    )
    return {
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


@router.get("/replacement-cutting")
def replacement_cutting_page(
    db: DbSession,
    current: CurrentUser,
    dept: Annotated[str, Query()],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    department = _resolve_department(db, current, dept)
    if department.code not in {"CUT", DEPT_ECO_COTTON_CUTTING}:
        raise HTTPException(404, "Replacement cutting queue not found")
    _require_inbox_department_permission(department, current)
    rows, total, _replacement_work_order_ids = _replacement_cutting_work_payload(
        db,
        int(department.id),
        limit,
        offset,
        set(),
    )
    return {
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


@router.get("")
def department_inbox(
    db: DbSession,
    current: CurrentUser,
    dept: str | None = None,
    tz: str | None = None,
    include_awaiting_packaging: bool = True,
    ready_to_ship_limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    ready_to_ship_offset: Annotated[int, Query(ge=0)] = 0,
    replacement_cutting_limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    replacement_cutting_offset: Annotated[int, Query(ge=0)] = 0,
    include_replacement_sewing: bool = True,
):
    d = _resolve_department(db, current, dept)
    operation = _DEPT_OPERATION.get(d.code)
    required = WORK_ORDER_OPERATION_PERMISSIONS.get(operation or "", set())
    granted = set(user_permissions(current))
    if required and "*" not in granted and not required.intersection(granted):
        raise HTTPException(403, f"Missing permission for {d.code} department inbox")
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
    queue_work_orders = work_orders
    if d.code in {"CUT", DEPT_ECO_COTTON_CUTTING}:
        progressed_order_ids = _orders_progressed_beyond_cutting(
            db,
            [int(work_order.production_order_id) for work_order in work_orders],
        )
        if d.code == DEPT_ECO_COTTON_CUTTING:
            # Usluga releases approved batches to Sewing independently. Keep the
            # parent Cutting work visible until Cutting itself is explicitly
            # completed so operators can continue adding later batches.
            progressed_order_ids.difference_update(
                _open_usluga_cutting_order_ids(
                    db,
                    [int(work_order.production_order_id) for work_order in work_orders],
                )
            )
        queue_work_orders = [
            work_order
            for work_order in work_orders
            if int(work_order.production_order_id) not in progressed_order_ids
        ]
    pending_work_orders = [w for w in queue_work_orders if w.status in _PENDING_WO_STATUSES]
    in_progress_work_orders = [w for w in queue_work_orders if w.status in _IN_PROGRESS_WO_STATUSES]
    active = [w for w in queue_work_orders if w.status in (*_PENDING_WO_STATUSES, *_IN_PROGRESS_WO_STATUSES)]
    work_order_po_ids = [int(w.production_order_id) for w in work_orders if w.production_order_id]
    received_by_po = _received_bundle_totals_by_po(
        db,
        [
            int(w.production_order_id)
            for w in work_orders
            if w.operation in {"cutting", "sewing"}
        ],
    )
    material_by_po = _material_payload_by_production_order(db, work_order_po_ids)
    production_context_by_po = _production_context_by_production_order(db, work_order_po_ids)
    blocked = [w for w in queue_work_orders if bool(w.is_blocked)]
    overdue = [
        w
        for w in queue_work_orders
        if as_utc(w.deadline)
        and w.status not in ("completed", "rejected", "cancelled")
        and as_utc(w.deadline) < now
    ]
    needs_qc = [w for w in queue_work_orders if int(w.failed_qty or 0) > 0]
    done_today = [
        w
        for w in work_orders
        if w.status == "completed"
        and w.end_time
        and as_utc(w.end_time)
        and as_utc(w.end_time).astimezone(client_tz).date() == today_client
    ]
    if d.code in {"CUT", DEPT_ECO_COTTON_CUTTING}:
        replacement_cutting_work, replacement_cutting_total, replacement_work_order_ids = (
            _replacement_cutting_work_payload(
                db,
                int(d.id),
                replacement_cutting_limit,
                replacement_cutting_offset,
                {int(work_order.id) for work_order in work_orders},
            )
        )
    else:
        replacement_cutting_work = []
        replacement_cutting_total = 0
        replacement_work_order_ids = set()
    if include_replacement_sewing and d.code in _SEWING_LOGISTICS_DEPTS:
        replacement_sewing_work, replacement_sewing_total = _replacement_sewing_work_payload(
            db, inbox_department_ids, textile_filter,
        )
    else:
        replacement_sewing_work = []
        replacement_sewing_total = None
    if replacement_work_order_ids:
        pending_work_orders = [w for w in pending_work_orders if int(w.id) not in replacement_work_order_ids]
        in_progress_work_orders = [w for w in in_progress_work_orders if int(w.id) not in replacement_work_order_ids]
        active = [w for w in active if int(w.id) not in replacement_work_order_ids]

    awaiting_packaging = []
    if include_awaiting_packaging and d.code in {"PKG", DEPT_BESTTEX_PACKAGING, DEPT_ECO_COTTON_PACKAGING}:
        awaiting_packaging, _ = _awaiting_packaging_rows(db, int(d.id))

    pending_packages = []
    ready_packages = []
    pending_packages_total = 0
    ready_packages_total = 0
    ready_to_ship = []
    ready_to_ship_total = 0
    if d.code == "FGS":
        package_list_columns = (
            Package.id,
            Package.package_no,
            Package.sales_order_id,
            Package.total_quantity,
            Package.status,
        )
        packed_rows = db.query(Package, func.count(Package.id).over()).options(
            load_only(*package_list_columns)
        ).filter(Package.status == "packed").order_by(Package.id.desc()).limit(50).all()
        pending_packages_total = int(packed_rows[0][1]) if packed_rows else 0
        packed = [package for package, _total in packed_rows]
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
        ready_statuses = ("received_in_storage", "reserved")
        ready_rows = db.query(Package, func.count(Package.id).over()).options(
            load_only(*package_list_columns)
        ).filter(Package.status.in_(ready_statuses)).order_by(Package.id.desc()).limit(50).all()
        ready_packages_total = int(ready_rows[0][1]) if ready_rows else 0
        ready = [package for package, _total in ready_rows]
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
        selected_order_ids: list[int] | None = None
        if ready_to_ship_limit is not None:
            ready_package_statuses = ("received_in_storage", "reserved")
            eligible_order_totals = (
                db.query(
                    StockReservation.sales_order_id.label("sales_order_id"),
                    func.sum(
                        case(
                            (Package.status.in_(ready_package_statuses), StockReservation.quantity),
                            else_=0,
                        )
                    ).label("quantity"),
                    func.sum(
                        case(
                            (
                                or_(
                                    Package.status.is_(None),
                                    Package.status.notin_(ready_package_statuses),
                                ),
                                StockReservation.quantity,
                            ),
                            else_=0,
                        )
                    ).label("pending_qty"),
                )
                .join(SalesOrder, SalesOrder.id == StockReservation.sales_order_id)
                .outerjoin(Package, Package.id == StockReservation.package_id)
                .filter(
                    SalesOrder.order_type == "branded_stock_sale",
                    SalesOrder.status.in_(["ready", "reserved"]),
                )
                .group_by(StockReservation.sales_order_id)
                .having(
                    or_(
                        func.sum(
                            case(
                                (Package.status.in_(ready_package_statuses), StockReservation.quantity),
                                else_=0,
                            )
                        ) > 0,
                        func.sum(
                            case(
                                (
                                    or_(
                                        Package.status.is_(None),
                                        Package.status.notin_(ready_package_statuses),
                                    ),
                                    StockReservation.quantity,
                                ),
                                else_=0,
                            )
                        ) > 0,
                    )
                )
                .subquery()
            )
            ready_to_ship_total = int(
                db.query(func.count()).select_from(eligible_order_totals).scalar() or 0
            )
            eligible_orders_query = db.query(eligible_order_totals.c.sales_order_id).order_by(
                eligible_order_totals.c.sales_order_id.asc()
            )
            eligible_orders_query = eligible_orders_query.offset(ready_to_ship_offset).limit(
                ready_to_ship_limit
            )
            selected_order_ids = [int(row[0]) for row in eligible_orders_query.all()]

        grouped: dict[int, dict] = {}
        reservation_query = (
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
        )
        if selected_order_ids is not None:
            reservation_query = reservation_query.filter(
                StockReservation.sales_order_id.in_(selected_order_ids)
            )
        reservation_rows = reservation_query.all()
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
        so_ids = selected_order_ids if selected_order_ids is not None else list(grouped)
        if so_ids:
            item_rows = (
                db.query(SalesOrderItem, Model).options(
                    load_only(
                        SalesOrderItem.id,
                        SalesOrderItem.sales_order_id,
                        SalesOrderItem.model_id,
                        SalesOrderItem.color,
                        SalesOrderItem.size,
                        SalesOrderItem.quantity,
                    ),
                    load_only(Model.id, Model.code, Model.name),
                )
                .join(Model, Model.id == SalesOrderItem.model_id)
                .filter(SalesOrderItem.sales_order_id.in_(so_ids))
                .order_by(SalesOrderItem.sales_order_id.asc(), SalesOrderItem.id.asc())
                .all()
            )
            for item, model in item_rows:
                order_row = grouped.get(int(item.sales_order_id))
                if not order_row:
                    continue
                quantity = max(0, int(item.quantity or 0))
                order_row.setdefault("item_lines", []).append(
                    {
                        "id": int(item.id),
                        "model_id": int(item.model_id),
                        "model_code": model.code,
                        "model_name": model.name,
                        "color": item.color,
                        "size": item.size,
                        "quantity": quantity,
                    }
                )
                order_row["order_quantity"] = int(order_row.get("order_quantity") or 0) + quantity
            latest_shipments = (
                db.query(
                    Shipment.sales_order_id.label("sales_order_id"),
                    Shipment.id.label("shipment_id"),
                    Shipment.shipment_no.label("shipment_no"),
                    Shipment.status.label("shipment_status"),
                    func.row_number().over(
                        partition_by=Shipment.sales_order_id,
                        order_by=Shipment.id.desc(),
                    ).label("shipment_rank"),
                )
                .filter(Shipment.sales_order_id.in_(so_ids))
                .subquery()
            )
            latest_by_so = {
                int(sh.sales_order_id): sh
                for sh in db.query(latest_shipments).filter(
                    latest_shipments.c.shipment_rank == 1
                )
            }
            for so_id, row in grouped.items():
                sh = latest_by_so.get(int(so_id))
                if not sh:
                    continue
                row["shipment_id"] = int(sh.shipment_id)
                row["shipment_no"] = sh.shipment_no
                row["shipment_status"] = sh.shipment_status
        ordered_groups = (
            (grouped[so_id] for so_id in selected_order_ids if so_id in grouped)
            if selected_order_ids is not None
            else (group for group in sorted(grouped.values(), key=lambda x: int(x["sales_order_id"])))
        )
        ready_to_ship = [
            {k: v for k, v in group.items() if k != "_ready_package_ids"}
            for group in ordered_groups
            if int(group.get("quantity") or 0) > 0 or int(group.get("pending_qty") or 0) > 0
        ]
        if selected_order_ids is None:
            ready_to_ship_total = len(ready_to_ship)

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
        "replacement_cutting_work_total": replacement_cutting_total,
        "replacement_cutting_work_has_more": (
            replacement_cutting_limit is not None
            and replacement_cutting_offset + len(replacement_cutting_work) < replacement_cutting_total
        ),
        "replacement_sewing_work": replacement_sewing_work,
        "replacement_sewing_work_total": replacement_sewing_total,
        "cutting_work_orders": [
            _work_order_card_payload(w, received_by_po, None, material_by_po, production_context_by_po)
            for w in work_orders
            if w.operation == "cutting" and w.status not in {"rejected", "cancelled"}
        ] if d.code in {"CUT", DEPT_ECO_COTTON_CUTTING} else [],
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
        "pending_packages_total": pending_packages_total,
        "ready_packages_total": ready_packages_total,
        "ready_to_ship": ready_to_ship,
        "ready_to_ship_total": ready_to_ship_total,
    }
