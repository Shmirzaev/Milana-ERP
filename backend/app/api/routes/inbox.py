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
    WorkOrder,
)

router = APIRouter(prefix="/inbox", tags=["inbox"])
_PENDING_WO_STATUSES = ("new", "planning", "ready", "waiting", "pending", "collected", "paused")
_IN_PROGRESS_WO_STATUSES = ("in_progress",)
_DEPT_OPERATION = {
    "CUT": "cutting",
    "PRT": "printing",
    "SEW": "sewing",
    "PKG": "packaging",
    "FGS": "storage_transfer",
}
_SEWING_LOGISTICS_DEPTS = {"SEW", "MIL", "BST"}
_WORKFLOW_SEQUENCE = ["cutting", "printing", "sewing", "packaging", "storage_transfer"]


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


def _incoming_work_items(db: DbSession, dept_code: str) -> list[dict]:
    target_operation = _DEPT_OPERATION.get(dept_code)
    if not target_operation:
        return []

    target_rows = (
        db.query(WorkOrder)
        .filter(
            WorkOrder.operation == target_operation,
            WorkOrder.status.notin_(["completed", "rejected", "cancelled"]),
        )
        .order_by(WorkOrder.id.desc())
        .limit(500)
        .all()
    )
    po_ids = [int(w.production_order_id) for w in target_rows]
    if not po_ids:
        return []

    all_rows = db.query(WorkOrder).filter(WorkOrder.production_order_id.in_(po_ids)).all()
    by_po: dict[int, dict[str, WorkOrder]] = {}
    for row in all_rows:
        by_po.setdefault(int(row.production_order_id), {})[str(row.operation)] = row

    po_rows = db.query(ProductionOrder).filter(ProductionOrder.id.in_(po_ids)).all()
    po_by_id = {int(po.id): po for po in po_rows}

    incoming: list[dict] = []
    for target in target_rows:
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
            }
        )
    return sorted(incoming, key=lambda row: (0 if int(row["ready_qty"] or 0) > 0 else 1, -int(row["work_order_id"])))[:200]


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

    incoming_bundle_statuses = ["sent_to_printing", "sent_to_sewing"]
    if d.code in _SEWING_LOGISTICS_DEPTS:
        incoming_bundle_statuses.append("created")

    incoming_bundles = (
        db.query(Bundle)
        .filter(
            Bundle.next_department_id == d.id,
            Bundle.status.in_(incoming_bundle_statuses),
        )
        .order_by(Bundle.id.desc())
        .limit(200)
        .all()
    )
    bundle_po_ids = [int(b.production_order_id) for b in incoming_bundles]
    bundle_po_by_id = {
        int(po.id): po
        for po in db.query(ProductionOrder).filter(ProductionOrder.id.in_(bundle_po_ids)).all()
    } if bundle_po_ids else {}
    bundle_production_no_by_id = {
        po_id: po.production_no
        for po_id, po in bundle_po_by_id.items()
    }
    incoming_work_orders = _incoming_work_items(db, d.code)

    work_orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.department_id == d.id)
        .order_by(WorkOrder.id.desc())
        .limit(500)
        .all()
    )
    pending_work_orders = [w for w in work_orders if w.status in _PENDING_WO_STATUSES]
    in_progress_work_orders = [w for w in work_orders if w.status in _IN_PROGRESS_WO_STATUSES]
    active = [w for w in work_orders if w.status in (*_PENDING_WO_STATUSES, *_IN_PROGRESS_WO_STATUSES)]
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

    awaiting_packaging = []
    if d.code == "PKG":
        sewing_rows = db.query(WorkOrder).filter(WorkOrder.operation == "sewing").all()
        by_po_sew = {w.production_order_id: int(w.passed_qty or 0) for w in sewing_rows}
        by_po_pkg = {
            w.production_order_id: int(w.passed_qty or 0)
            for w in db.query(WorkOrder).filter(WorkOrder.operation == "packaging").all()
        }
        for po_id, sewn in by_po_sew.items():
            already_packed = by_po_pkg.get(po_id, 0)
            if sewn - already_packed <= 0:
                continue
            po = db.get(ProductionOrder, po_id)
            awaiting_packaging.append(
                {
                    "production_order_id": po_id,
                    "production_no": po.production_no if po else None,
                    "ready_qty": sewn - already_packed,
                    "sewn_passed": sewn,
                    "already_packed": already_packed,
                }
            )

    pending_packages = []
    ready_packages = []
    ready_to_ship = []
    if d.code == "FGS":
        packed = db.query(Package).filter(Package.status == "packed").order_by(Package.id.desc()).limit(200).all()
        pending_packages = [
            {
                "id": p.id,
                "package_no": p.package_no,
                "sales_order_id": p.sales_order_id,
                "total_quantity": p.total_quantity,
            }
            for p in packed
        ]
        ready = db.query(Package).filter(Package.status.in_(["received_in_storage", "reserved"])).all()
        ready_packages = [
            {
                "id": p.id,
                "package_no": p.package_no,
                "sales_order_id": p.sales_order_id,
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
                "model_id": b.model_id,
                "color": b.color,
                "size": b.size,
                "quantity": b.quantity,
                "status": b.status,
                "sewing_factory_code": b.sewing_factory_code,
            }
            for b in incoming_bundles
        ],
        "incoming_work_orders": incoming_work_orders,
        "active_work_orders": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "status": w.status,
                "planned_output_qty": w.planned_output_qty,
                "passed_qty": w.passed_qty,
                "failed_qty": w.failed_qty,
                "deadline": w.deadline,
                "is_blocked": w.is_blocked,
                "block_reason": w.block_reason,
            }
            for w in active
        ],
        "pending_work_orders": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "status": w.status,
                "planned_output_qty": w.planned_output_qty,
                "passed_qty": w.passed_qty,
                "failed_qty": w.failed_qty,
                "deadline": w.deadline,
                "is_blocked": w.is_blocked,
                "block_reason": w.block_reason,
            }
            for w in pending_work_orders
        ],
        "in_progress_work_orders": [
            {
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "status": w.status,
                "planned_output_qty": w.planned_output_qty,
                "passed_qty": w.passed_qty,
                "failed_qty": w.failed_qty,
                "deadline": w.deadline,
                "is_blocked": w.is_blocked,
                "block_reason": w.block_reason,
            }
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
                "id": w.id,
                "production_order_id": w.production_order_id,
                "operation": w.operation,
                "passed_qty": w.passed_qty,
                "end_time": w.end_time,
            }
            for w in done_today
        ],
        "awaiting_packaging": awaiting_packaging,
        "pending_packages": pending_packages,
        "ready_packages": ready_packages,
        "ready_to_ship": ready_to_ship,
    }
