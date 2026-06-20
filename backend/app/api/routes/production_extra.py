"""Extra production endpoints: assignments split across flows, block/unblock,
capacity utilization, PDF/HTML export of the process-tracking view.
"""
from datetime import datetime, timezone, timedelta
from html import escape
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.models import (
    WorkOrder, SewingFlow, SewingAssignment, ProductionOrder, Model, User,
    Customer, SalesOrder,
)
from app.schemas.sewing_assignment import (
    SewingAssignmentIn, SewingAssignmentUpdate, SewingAssignmentOut,
)
from app.core.dt import as_utc
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(tags=["production_extra"])
_ACTIVE_WO_STATUSES = ("waiting", "pending", "collected", "ready", "in_progress", "paused", "new", "planning")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")
# Blocking/unblocking a work order is a planning/management action.
_WO_BLOCK_PERMS = (
    "planning.production",
    "sewing.flows",
    "cutting.records",
    "printing.records",
    "sewing.records",
    "packaging.records",
    "management.approve",
    "*",
)


def _h(value) -> str:
    return escape(str(value or ""), quote=True)


class BlockIn(BaseModel):
    reason: Optional[str] = None


# ===== Block / Unblock =====
@router.post("/work-orders/{wid}/block")
def block_wo(wid: int, payload: BlockIn, db: DbSession, current: User = Depends(require_permissions(*_WO_BLOCK_PERMS))):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    reason = (payload.reason or "Blocked").strip()
    wo.is_blocked = True
    wo.block_reason = reason
    log_action(db, current, "block", "WorkOrder", wo.id, new_value={"reason": reason})
    # Notify the PO creator (typically Planning) so they can act on the block.
    po = db.get(ProductionOrder, wo.production_order_id)
    if po and po.created_by and po.created_by != current.id:
        notify(db, user_id=po.created_by,
               title=f"Blocked: {wo.operation} order {wo.order_no or wo.id}",
               message=reason,
               link=f"/work-orders/{wo.id}/{wo.operation}")
    db.commit()
    db.refresh(wo)
    return {"id": wo.id, "is_blocked": True, "block_reason": wo.block_reason}


@router.post("/work-orders/{wid}/unblock")
def unblock_wo(wid: int, db: DbSession, current: User = Depends(require_permissions(*_WO_BLOCK_PERMS))):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    wo.is_blocked = False
    wo.block_reason = None
    log_action(db, current, "unblock", "WorkOrder", wo.id)
    db.commit()
    return {"id": wo.id, "is_blocked": False}


# ===== Sewing Assignments (parallel-line splitting) =====
@router.get("/work-orders/{wid}/assignments", response_model=list[SewingAssignmentOut])
def list_assignments(wid: int, db: DbSession, _: CurrentUser):
    if not db.get(WorkOrder, wid):
        raise HTTPException(404, "Work order not found")
    return db.query(SewingAssignment).filter(SewingAssignment.work_order_id == wid).order_by(SewingAssignment.id).all()


@router.post("/work-orders/{wid}/assignments", response_model=SewingAssignmentOut, status_code=201)
def create_assignment(
    wid: int, payload: SewingAssignmentIn, db: DbSession,
    current: User = Depends(require_permissions("planning.production", "sewing.flows", "sewing.records", "*")),
):
    wo = db.get(WorkOrder, wid)
    if not wo: raise HTTPException(404, "Work order not found")
    if wo.operation != "sewing":
        raise HTTPException(400, "Assignments only apply to sewing work orders")
    flow = db.get(SewingFlow, payload.sewing_flow_id)
    if not flow: raise HTTPException(404, "Sewing flow not found")
    if payload.quantity <= 0:
        raise HTTPException(400, "Quantity must be > 0")

    # Validate: total of all assignments cannot exceed planned_input_qty.
    existing = db.query(SewingAssignment).filter(SewingAssignment.work_order_id == wid).all()
    already = sum(a.quantity for a in existing)
    if already + payload.quantity > (wo.planned_input_qty or 0) and not is_admin(current):
        raise HTTPException(
            400,
            f"Total assignments ({already + payload.quantity}) exceeds planned work-order input ({wo.planned_input_qty}). "
            "Admin can override.",
        )

    # Soft capacity warning — append to response, do not block.
    capacity_warning = _capacity_warning(db, flow, payload.quantity, payload.planned_start, payload.planned_end)
    if capacity_warning:
        raise HTTPException(409, capacity_warning)

    a = SewingAssignment(
        work_order_id=wid,
        sewing_flow_id=payload.sewing_flow_id,
        quantity=payload.quantity,
        planned_start=payload.planned_start,
        planned_end=payload.planned_end,
        notes=payload.notes,
        created_by=current.id,
    )
    db.add(a); db.flush()

    # If WO has no primary sewing_flow yet, set it to the first assignment for convenience.
    if not wo.sewing_flow_id:
        wo.sewing_flow_id = payload.sewing_flow_id

    log_action(db, current, "create", "SewingAssignment", a.id, new_value={
        "work_order_id": wid, "sewing_flow_id": payload.sewing_flow_id, "quantity": payload.quantity,
        "capacity_warning": capacity_warning,
    })
    db.commit(); db.refresh(a)
    return a


@router.patch("/sewing-assignments/{aid}", response_model=SewingAssignmentOut)
def update_assignment(
    aid: int, payload: SewingAssignmentUpdate, db: DbSession,
    current: User = Depends(require_permissions("planning.production", "sewing.flows", "*")),
):
    a = db.get(SewingAssignment, aid)
    if not a: raise HTTPException(404, "Assignment not found")
    changes = payload.model_dump(exclude_unset=True)
    wo = db.get(WorkOrder, a.work_order_id)
    if not wo:
        raise HTTPException(404, "Work order not found")

    next_flow_id = changes.get("sewing_flow_id", a.sewing_flow_id)
    next_qty = int(changes.get("quantity", a.quantity))
    next_start = changes.get("planned_start", a.planned_start)
    next_end = changes.get("planned_end", a.planned_end)
    if next_qty <= 0:
        raise HTTPException(400, "Quantity must be > 0")
    flow = db.get(SewingFlow, next_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing flow not found")

    siblings = db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id == a.work_order_id,
        SewingAssignment.id != a.id,
    ).all()
    already = sum(s.quantity for s in siblings)
    if already + next_qty > (wo.planned_input_qty or 0) and not is_admin(current):
        raise HTTPException(
            400,
            f"Total assignments ({already + next_qty}) exceeds planned work-order input ({wo.planned_input_qty}). "
            "Admin can override.",
        )

    capacity_warning = _capacity_warning(
        db,
        flow,
        next_qty,
        next_start,
        next_end,
        exclude_assignment_id=a.id,
    )
    if capacity_warning:
        raise HTTPException(409, capacity_warning)

    previous_flow = a.sewing_flow_id
    for k, v in changes.items():
        setattr(a, k, v)
    if changes.get("status") == "completed" and not a.actual_end:
        a.actual_end = datetime.now(timezone.utc)
    log_action(db, current, "update", "SewingAssignment", a.id, new_value=changes)
    if "sewing_flow_id" in changes and changes["sewing_flow_id"] != previous_flow:
        # Audit the transfer specifically — useful for line-breakdown investigations.
        log_action(db, current, "transfer", "SewingAssignment", a.id, new_value={
            "from_flow": previous_flow, "to_flow": changes["sewing_flow_id"],
        })
    db.commit(); db.refresh(a)
    return a


@router.delete("/sewing-assignments/{aid}", status_code=204)
def delete_assignment(
    aid: int, db: DbSession,
    current: User = Depends(require_permissions("planning.production", "sewing.flows", "*")),
):
    a = db.get(SewingAssignment, aid)
    if not a: raise HTTPException(404, "Assignment not found")
    db.delete(a)
    log_action(db, current, "delete", "SewingAssignment", aid)
    db.commit()


# ===== Capacity utilization per flow =====
def _project_daily_load(
    db: DbSession,
    flow: SewingFlow,
    qty: int,
    start,
    end,
    *,
    exclude_assignment_id: int | None = None,
) -> tuple[float, float] | None:
    """Return projected daily load and capacity for the window."""
    start = as_utc(start)
    end = as_utc(end)
    if not flow.capacity_per_day or not start or not end:
        return None
    days = max(1.0, (end - start).total_seconds() / 86400.0)
    daily_needed = qty / days
    qry = db.query(SewingAssignment).filter(
        SewingAssignment.sewing_flow_id == flow.id,
        SewingAssignment.status.in_(["planned", "in_progress"]),
    )
    # Keep validation consistent with the utilization widgets: only active WOs
    # should consume today's capacity.
    qry = qry.join(WorkOrder, WorkOrder.id == SewingAssignment.work_order_id).filter(
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    )
    if exclude_assignment_id:
        qry = qry.filter(SewingAssignment.id != exclude_assignment_id)
    existing = qry.all()
    committed = 0.0
    for a in existing:
        remaining_qty = max(0, int(a.quantity or 0) - int(a.completed_qty or 0))
        if remaining_qty <= 0:
            continue
        a_start = as_utc(a.planned_start)
        a_end = as_utc(a.planned_end)
        if not a_start or not a_end:
            continue
        if a_end < start or a_start > end:
            continue
        a_days = max(1.0, (a_end - a_start).total_seconds() / 86400.0)
        committed += remaining_qty / a_days
    return daily_needed + committed, float(flow.capacity_per_day)


def _capacity_warning(
    db: DbSession,
    flow: SewingFlow,
    qty: int,
    start,
    end,
    *,
    exclude_assignment_id: int | None = None,
) -> str | None:
    """Return warning when assignment projection exceeds flow capacity."""
    projection = _project_daily_load(
        db,
        flow,
        qty,
        start,
        end,
        exclude_assignment_id=exclude_assignment_id,
    )
    if not projection:
        return None
    projected, capacity = projection
    if projected > capacity:
        return (
            f"Capacity full: {flow.code} daily load would be {round(projected)} "
            f"vs capacity {int(capacity)}"
        )
    return None


@router.get("/sewing-flows/{fid}/utilization")
def flow_utilization(fid: int, db: DbSession, _: CurrentUser):
    f = db.get(SewingFlow, fid)
    if not f: raise HTTPException(404, "Flow not found")
    now = datetime.now(timezone.utc)
    rows = db.query(SewingAssignment).join(
        WorkOrder, WorkOrder.id == SewingAssignment.work_order_id
    ).filter(
        SewingAssignment.sewing_flow_id == fid,
        SewingAssignment.status.in_(["planned", "in_progress"]),
        WorkOrder.status.in_(_ACTIVE_WO_STATUSES),
    ).all()
    committed_today = 0
    for a in rows:
        remaining_qty = max(0, int(a.quantity or 0) - int(a.completed_qty or 0))
        if remaining_qty <= 0:
            continue
        a_start = as_utc(a.planned_start)
        a_end = as_utc(a.planned_end)
        if not a_start or not a_end:
            continue
        if a_start <= now <= a_end:
            days = max(1.0, (a_end - a_start).total_seconds() / 86400.0)
            committed_today += round(remaining_qty / days)
    # Add directly assigned sewing WOs that are not split.
    direct_wos = db.query(WorkOrder).filter(
        WorkOrder.sewing_flow_id == fid,
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
        committed_today += max(0, int(w.planned_output_qty or 0) - int(w.passed_qty or 0))
    pct = (committed_today / f.capacity_per_day * 100) if f.capacity_per_day else 0
    return {
        "flow_id": fid, "code": f.code,
        "capacity_per_day": f.capacity_per_day,
        "committed_today": committed_today,
        "utilization_pct": round(pct, 1),
    }


# ===== PDF (HTML) export of process tracking =====
@router.get("/process-tracking/export", response_class=HTMLResponse)
def export_process_html(db: DbSession, _: CurrentUser):
    """A printable HTML view (use browser's "Save as PDF" — keeps deps minimal)."""
    pos = db.query(ProductionOrder).filter(
        ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]),
    ).options(
        selectinload(ProductionOrder.work_orders),
    ).order_by(ProductionOrder.id.desc()).all()

    rows_html = ""
    for po in pos:
        model = db.get(Model, po.model_id)
        so = db.get(SalesOrder, po.sales_order_id) if po.sales_order_id else None
        cust = db.get(Customer, so.customer_id) if so and so.customer_id else None
        stages = " &middot; ".join(
            f"{_h(w.operation)}[{_h(w.status)}] {_h(w.passed_qty)}/{_h(w.planned_output_qty)}"
            for w in sorted(po.work_orders, key=lambda x: x.id)
        ) or "&mdash;"
        dl = _h(po.deadline.strftime("%Y-%m-%d") if po.deadline else "")
        rows_html += f"""
          <tr>
            <td><b>{_h(po.order_no)}</b></td>
            <td>{_h(cust.name if cust else '')}</td>
            <td>{_h(model.code if model else po.model_id)}<br><span class='sub'>{_h(model.name if model else '')}</span></td>
            <td style='text-align:right'>{_h(po.planned_quantity)}</td>
            <td>{_h(po.status)}</td>
            <td>{dl}</td>
            <td>{stages}</td>
          </tr>
        """

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Milana ERP — Process Tracking</title>
<style>
  body{{font-family:Arial,sans-serif;margin:20mm 12mm;color:#0f172a}}
  h1{{margin:0 0 4mm 0;color:#1e3a8a}}
  table{{width:100%;border-collapse:collapse;font-size:10pt;margin-top:4mm}}
  th,td{{border:1px solid #cbd5e1;padding:4mm;text-align:left;vertical-align:top}}
  th{{background:#f1f5f9;text-transform:uppercase;font-size:8pt;letter-spacing:0.5pt}}
  .sub{{color:#64748b;font-size:8pt}}
  @media print {{ button{{display:none}} }}
</style></head>
<body>
  <h1>Milana ERP — Process Tracking</h1>
  <div class='sub'>Generated {now}</div>
  <table>
    <thead><tr>
      <th>Order</th><th>Customer</th><th>Model</th><th>Qty</th>
      <th>Status</th><th>Deadline</th><th>Stages</th>
    </tr></thead>
    <tbody>{rows_html or '<tr><td colspan=7>No active production orders.</td></tr>'}</tbody>
  </table>
  <button onclick="window.print()" style="margin-top:6mm;padding:3mm 8mm;background:#1d4ed8;color:#fff;border:none;border-radius:2mm">Print / Save as PDF</button>
</body></html>"""
    return HTMLResponse(content=html)
