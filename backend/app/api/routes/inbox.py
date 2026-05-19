from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentUser, DbSession
from app.core.dt import as_utc
from app.models import Bundle, Department, Package, ProductionOrder, WorkOrder

router = APIRouter(prefix="/inbox", tags=["inbox"])
_PENDING_WO_STATUSES = ("new", "planning", "ready", "waiting", "pending", "collected", "paused")
_IN_PROGRESS_WO_STATUSES = ("in_progress",)


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

    incoming_bundles = (
        db.query(Bundle)
        .filter(
            Bundle.next_department_id == d.id,
            Bundle.status.in_(["sent_to_printing", "sent_to_sewing"]),
        )
        .order_by(Bundle.id.desc())
        .limit(200)
        .all()
    )

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
        grouped: dict[int | None, dict] = {}
        for p in ready:
            g = grouped.setdefault(
                p.sales_order_id,
                {"sales_order_id": p.sales_order_id, "packages": 0, "quantity": 0},
            )
            g["packages"] += 1
            g["quantity"] += int(p.total_quantity or 0)
        ready_to_ship = list(grouped.values())

    return {
        "department": {"id": d.id, "code": d.code, "name": d.name},
        "incoming_bundles": [
            {
                "id": b.id,
                "bundle_no": b.bundle_no,
                "production_order_id": b.production_order_id,
                "model_id": b.model_id,
                "color": b.color,
                "size": b.size,
                "quantity": b.quantity,
                "status": b.status,
            }
            for b in incoming_bundles
        ],
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
        "ready_to_ship": ready_to_ship,
    }
