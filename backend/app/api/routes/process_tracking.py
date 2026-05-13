"""Cross-department process tracking.

Returns, for every active sales order, the current stage of each linked
production order — which department is working on it, how many units are
done vs planned, deadlines, and overdue flags.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.models import (
    SalesOrder, ProductionOrder, WorkOrder, Customer, Model, SewingFlow, User,
)

router = APIRouter(prefix="/process-tracking", tags=["process-tracking"])


def _can_view(user: User) -> bool:
    if is_admin(user):
        return True
    if user.role and user.role.name in ("Admin", "Management", "Sales", "Planning"):
        return True
    perms = (user.role.permissions if user.role else []) or []
    return any(p in perms for p in ("processes.view", "sales.orders", "planning.production"))


@router.get("")
def list_processes(
    db: DbSession, current: CurrentUser,
    status: str | None = None,
    only_active: bool = True,
):
    """One row per Production Order with rolled-up stage progress."""
    if not _can_view(current):
        raise HTTPException(403, "Not allowed to view process tracking")

    # Use selectinload — joinedload on two collections produces a Cartesian product.
    qry = db.query(ProductionOrder).options(
        selectinload(ProductionOrder.work_orders),
        selectinload(ProductionOrder.items),
    )
    if status:
        qry = qry.filter(ProductionOrder.status == status)
    if only_active:
        qry = qry.filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))

    now = datetime.now(timezone.utc)
    out = []
    for po in qry.order_by(ProductionOrder.id.desc()).all():
        # Resolve display labels
        model = db.get(Model, po.model_id)
        so = db.get(SalesOrder, po.sales_order_id) if po.sales_order_id else None
        customer = db.get(Customer, so.customer_id) if so and so.customer_id else None

        stages = []
        for wo in sorted(po.work_orders, key=lambda w: w.id):
            flow = db.get(SewingFlow, wo.sewing_flow_id) if wo.sewing_flow_id else None
            deadline_dt = wo.deadline
            overdue = bool(deadline_dt and wo.status not in ("completed", "rejected", "cancelled") and deadline_dt < now)
            planned = wo.planned_output_qty or 0
            done = wo.passed_qty or 0
            pct = round(100.0 * done / planned, 1) if planned > 0 else 0.0
            stages.append({
                "work_order_id": wo.id,
                "operation": wo.operation,
                "department_id": wo.department_id,
                "status": wo.status,
                "planned": planned,
                "completed": done,
                "failed": wo.failed_qty or 0,
                "rework": wo.rework_qty or 0,
                "progress_pct": pct,
                "assigned_to": wo.assigned_to,
                "sewing_flow_id": wo.sewing_flow_id,
                "sewing_flow_code": flow.code if flow else None,
                "sewing_flow_name": flow.name if flow else None,
                "is_blocked": bool(wo.is_blocked),
                "block_reason": wo.block_reason,
                "deadline": deadline_dt,
                "overdue": overdue,
                "start_time": wo.start_time,
                "end_time": wo.end_time,
            })

        # "Blocked-by": find the first blocked stage if any.
        blocked = next((s for s in stages if s["is_blocked"]), None)

        # Determine the current active stage = first non-completed WO.
        # If no stages exist yet (work orders haven't been generated), the PO is
        # "planning_required" — Planning still needs to break it into work orders.
        current = next((s for s in stages if s["status"] not in ("completed", "rejected", "cancelled")), None)
        if not stages:
            current_stage_label = "planning_required"
            current_stage_status = po.status
        elif current is None:
            current_stage_label = "completed"
            current_stage_status = None
        else:
            current_stage_label = current["operation"]
            current_stage_status = current["status"]
        po_overdue = bool(po.deadline and po.status not in ("delivered", "closed", "cancelled") and po.deadline < now)

        out.append({
            "production_order_id": po.id,
            "production_no": po.production_no,
            "production_type": po.production_type,
            "po_status": po.status,
            "po_deadline": po.deadline,
            "po_overdue": po_overdue,
            "planned_quantity": po.planned_quantity,
            "sales_order_id": po.sales_order_id,
            "sales_order_no": so.order_no if so else None,
            "customer_id": so.customer_id if so else None,
            "customer_name": customer.name if customer else None,
            "model_id": po.model_id,
            "model_code": model.code if model else None,
            "model_name": model.name if model else None,
            "current_stage": current_stage_label,
            "current_stage_status": current_stage_status,
            "current_sewing_flow": current["sewing_flow_code"] if current else None,
            "is_blocked": blocked is not None,
            "blocked_by": {
                "work_order_id": blocked["work_order_id"], "operation": blocked["operation"],
                "reason": blocked["block_reason"],
            } if blocked else None,
            "stages": stages,
        })
    return out


@router.get("/summary")
def summary(db: DbSession, current: CurrentUser):
    """Counts per current stage — useful for the top-row cards on the page."""
    if not _can_view(current):
        raise HTTPException(403, "Not allowed")
    rows = db.query(ProductionOrder).filter(
        ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]),
    ).all()
    counts: dict[str, int] = {}
    for po in rows:
        counts[po.status] = counts.get(po.status, 0) + 1
    return {"counts": counts, "total_active": len(rows)}
