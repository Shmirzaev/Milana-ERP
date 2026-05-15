"""Cross-department process tracking.

Returns, for every active production order, the current stage of each linked
work order — which department is working on it, how many units are done vs
planned, deadlines, sewing-flow assignment, overdue and block flags.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, is_admin
from app.models import (
    SalesOrder, ProductionOrder, Customer, Model, SewingFlow, User,
)
from app.core.dt import as_utc

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
    """One row per Production Order with rolled-up stage progress.

    Uses bulk lookups for Model / SalesOrder / Customer / SewingFlow to avoid
    N+1 queries when there are many production orders.
    """
    if not _can_view(current):
        raise HTTPException(403, "Not allowed to view process tracking")

    qry = db.query(ProductionOrder).options(
        selectinload(ProductionOrder.work_orders),
        selectinload(ProductionOrder.items),
    )
    if status:
        qry = qry.filter(ProductionOrder.status == status)
    if only_active:
        qry = qry.filter(ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]))

    pos = qry.order_by(ProductionOrder.id.desc()).all()

    # Bulk-load related entities so we resolve names without N+1 queries.
    model_ids = {p.model_id for p in pos if p.model_id}
    so_ids = {p.sales_order_id for p in pos if p.sales_order_id}
    flow_ids = {w.sewing_flow_id for p in pos for w in p.work_orders if w.sewing_flow_id}

    models = {m.id: m for m in (db.query(Model).filter(Model.id.in_(model_ids)).all() if model_ids else [])}
    sos = {s.id: s for s in (db.query(SalesOrder).filter(SalesOrder.id.in_(so_ids)).all() if so_ids else [])}
    customer_ids = {s.customer_id for s in sos.values() if s.customer_id}
    customers = {c.id: c for c in (db.query(Customer).filter(Customer.id.in_(customer_ids)).all() if customer_ids else [])}
    flows = {f.id: f for f in (db.query(SewingFlow).filter(SewingFlow.id.in_(flow_ids)).all() if flow_ids else [])}

    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for po in pos:
        model = models.get(po.model_id)
        so = sos.get(po.sales_order_id) if po.sales_order_id else None
        customer = customers.get(so.customer_id) if so and so.customer_id else None

        stages: list[dict] = []
        for wo in sorted(po.work_orders, key=lambda w: w.id):
            flow = flows.get(wo.sewing_flow_id) if wo.sewing_flow_id else None
            deadline_dt = as_utc(wo.deadline)
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

        blocked = next((s for s in stages if s["is_blocked"]), None)
        current_stage = next((s for s in stages if s["status"] not in ("completed", "rejected", "cancelled")), None)
        if not stages:
            current_stage_label = "planning_required"
            current_stage_status = po.status
        elif current_stage is None:
            current_stage_label = "completed"
            current_stage_status = None
        else:
            current_stage_label = current_stage["operation"]
            current_stage_status = current_stage["status"]
        po_deadline_utc = as_utc(po.deadline)
        po_overdue = bool(po_deadline_utc and po.status not in ("delivered", "closed", "cancelled") and po_deadline_utc < now)

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
            "current_sewing_flow": current_stage["sewing_flow_code"] if current_stage else None,
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
    """Counts per status — useful for the top-row cards on the page."""
    if not _can_view(current):
        raise HTTPException(403, "Not allowed")
    rows = db.query(ProductionOrder).filter(
        ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]),
    ).all()
    counts: dict[str, int] = {}
    for po in rows:
        counts[po.status] = counts.get(po.status, 0) + 1
    return {"counts": counts, "total_active": len(rows)}
