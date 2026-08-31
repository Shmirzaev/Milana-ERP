"""Extra production endpoints: assignments split across flows, block/unblock,
capacity utilization, PDF/HTML export of the process-tracking view.
"""
from datetime import datetime, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.core.deps import DbSession, CurrentUser, require_permissions, is_admin
from app.models import (
    WorkOrder, SewingFlow, SewingAssignment, ProductionOrder, Model, User,
    Customer, SalesOrder, Bundle, ProductionBatch,
)
from app.schemas.sewing_assignment import (
    SewingAssignmentIn, SewingAssignmentUpdate, SewingAssignmentOut,
)
from app.core.dt import as_utc
from app.services.audit import log_action
from app.services.model_images import model_display_image_url
from app.services.notifications import notify
from app.services.bundles import resolve_sewing_factory_code
from app.services.factory_scope import require_factory_access
from app.services.payroll_factory_scope import production_order_factory_condition
from app.services.sewing_scope import require_sewing_flow_access

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


def _received_sewing_qty(db: DbSession, wo: WorkOrder, production_batch_id: int | None = None) -> int:
    qry = db.query(func.coalesce(func.sum(Bundle.quantity), 0)).filter(
        Bundle.production_order_id == wo.production_order_id,
        Bundle.status == "received_sewing",
    )
    scope_batch_id = production_batch_id if production_batch_id is not None else wo.production_batch_id
    if scope_batch_id is not None:
        qry = qry.filter(Bundle.production_batch_id == scope_batch_id)
    return int(qry.scalar() or 0)


def _normalize_assignment_batch_id(db: DbSession, wo: WorkOrder, production_batch_id: int | None) -> int | None:
    normalized = int(production_batch_id) if production_batch_id else None
    if wo.production_batch_id is not None:
        expected = int(wo.production_batch_id)
        if normalized is not None and normalized != expected:
            raise HTTPException(400, f"This work order is bound to batch #{expected}")
        return expected
    if normalized is None:
        return None
    exists = (
        db.query(ProductionBatch.id)
        .filter(
            ProductionBatch.id == normalized,
            ProductionBatch.production_order_id == wo.production_order_id,
        )
        .first()
    )
    if not exists:
        raise HTTPException(404, "Production batch not found for this production order")
    return normalized


def _sewing_assignment_limit(db: DbSession, wo: WorkOrder, production_batch_id: int | None = None) -> int:
    if production_batch_id is not None:
        batch_plan = int(
            db.query(func.coalesce(ProductionBatch.planned_quantity, 0))
            .filter(
                ProductionBatch.id == production_batch_id,
                ProductionBatch.production_order_id == wo.production_order_id,
            )
            .scalar()
            or 0
        )
        return max(0, batch_plan, _received_sewing_qty(db, wo, production_batch_id))
    return max(
        0,
        int(wo.planned_input_qty or 0),
        int(wo.planned_output_qty or 0),
        int(wo.actual_input_qty or 0),
        _received_sewing_qty(db, wo),
    )


def _received_sewing_factories(
    db: DbSession,
    wo: WorkOrder,
    production_batch_id: int | None,
) -> set[str]:
    routed_qry = db.query(Bundle.sewing_factory_code).filter(
        Bundle.production_order_id == wo.production_order_id,
        Bundle.status == "received_sewing",
    )
    if production_batch_id is not None:
        routed_qry = routed_qry.filter(Bundle.production_batch_id == production_batch_id)
    return {
        resolve_sewing_factory_code(factory_code)
        for (factory_code,) in routed_qry.distinct().all()
    }


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
    require_sewing_flow_access(current, flow)
    if not flow.is_active: raise HTTPException(400, "Sewing flow is inactive")
    if payload.quantity <= 0:
        raise HTTPException(400, "Quantity must be > 0")
    batch_id = _normalize_assignment_batch_id(db, wo, payload.production_batch_id)
    routed_factories = _received_sewing_factories(db, wo, batch_id)
    if routed_factories and routed_factories != {flow.factory_code}:
        raise HTTPException(409, "This sewing work is routed to a different sewing factory")

    # Validate: total assignments cannot exceed the selected batch/order input.
    existing_qry = db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id == wid,
        SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
    )
    if batch_id is None:
        existing_qry = existing_qry.filter(SewingAssignment.production_batch_id.is_(None))
    else:
        existing_qry = existing_qry.filter(SewingAssignment.production_batch_id == batch_id)
    existing = existing_qry.all()
    already = sum(a.quantity for a in existing)
    assignment_limit = _sewing_assignment_limit(db, wo, batch_id)
    if already + payload.quantity > assignment_limit and not is_admin(current):
        raise HTTPException(
            400,
            f"Total assignments ({already + payload.quantity}) exceeds available sewing input ({assignment_limit}). "
            "Admin can override.",
        )

    # Soft capacity warning — append to response, do not block.
    capacity_warning = None

    a = SewingAssignment(
        work_order_id=wid,
        production_batch_id=batch_id,
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
        "work_order_id": wid, "production_batch_id": batch_id, "sewing_flow_id": payload.sewing_flow_id, "quantity": payload.quantity,
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

    previous_flow = db.get(SewingFlow, a.sewing_flow_id)
    if not previous_flow:
        raise HTTPException(404, "Current sewing flow not found")
    require_sewing_flow_access(current, previous_flow)

    next_flow_id = changes.get("sewing_flow_id", a.sewing_flow_id)
    next_qty = int(changes.get("quantity", a.quantity))
    next_start = changes.get("planned_start", a.planned_start)
    next_end = changes.get("planned_end", a.planned_end)
    next_batch_id = _normalize_assignment_batch_id(db, wo, changes.get("production_batch_id", a.production_batch_id))
    if next_qty <= 0:
        raise HTTPException(400, "Quantity must be > 0")
    flow = db.get(SewingFlow, next_flow_id)
    if not flow:
        raise HTTPException(404, "Sewing flow not found")
    require_sewing_flow_access(current, flow)
    if not flow.is_active:
        raise HTTPException(400, "Sewing flow is inactive")
    is_transfer = int(flow.id) != int(previous_flow.id)
    if is_transfer and a.status not in ("planned", "in_progress"):
        raise HTTPException(409, "Only active sewing assignments can be moved")
    if is_transfer and flow.factory_code != previous_flow.factory_code:
        raise HTTPException(409, "Sewing work cannot be moved to another factory")
    routed_factories = _received_sewing_factories(db, wo, next_batch_id)
    if routed_factories and routed_factories != {flow.factory_code}:
        raise HTTPException(409, "This sewing work is routed to a different sewing factory")

    siblings = db.query(SewingAssignment).filter(
        SewingAssignment.work_order_id == a.work_order_id,
        SewingAssignment.id != a.id,
        SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
    ).all()
    if next_batch_id is None:
        siblings = [s for s in siblings if s.production_batch_id is None]
    else:
        siblings = [s for s in siblings if int(s.production_batch_id or 0) == next_batch_id]
    already = sum(s.quantity for s in siblings)
    assignment_limit = _sewing_assignment_limit(db, wo, next_batch_id)
    if already + next_qty > assignment_limit and not is_admin(current):
        raise HTTPException(
            400,
            f"Total assignments ({already + next_qty}) exceeds available sewing input ({assignment_limit}). "
            "Admin can override.",
        )

    capacity_warning = None

    previous_flow_id = int(a.sewing_flow_id)
    for k, v in changes.items():
        setattr(a, k, v)
    if a.production_batch_id != next_batch_id:
        a.production_batch_id = next_batch_id
        changes["production_batch_id"] = next_batch_id
    if changes.get("status") == "completed" and not a.actual_end:
        a.actual_end = datetime.now(timezone.utc)
    log_action(db, current, "update", "SewingAssignment", a.id, new_value=changes)
    primary_flow_updated = False
    if is_transfer and int(wo.sewing_flow_id or 0) == previous_flow_id:
        remaining_on_previous = db.query(SewingAssignment.id).filter(
            SewingAssignment.work_order_id == wo.id,
            SewingAssignment.id != a.id,
            SewingAssignment.sewing_flow_id == previous_flow_id,
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).first()
        if not remaining_on_previous:
            wo.sewing_flow_id = int(flow.id)
            primary_flow_updated = True
    if is_transfer:
        # Audit the transfer specifically — useful for line-breakdown investigations.
        log_action(db, current, "transfer", "SewingAssignment", a.id, new_value={
            "from_flow": previous_flow_id,
            "to_flow": int(flow.id),
            "work_order_primary_flow_updated": primary_flow_updated,
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


# ===== Printable HTML export of process tracking =====
@router.get("/process-tracking/export", response_class=HTMLResponse)
def export_process_html(db: DbSession, current: CurrentUser, factory: str | None = None):
    """A printable HTML view (use browser's "Save as PDF" — keeps deps minimal)."""
    qry = db.query(ProductionOrder).filter(
        ProductionOrder.status.not_in(["closed", "cancelled", "delivered"]),
    )
    if factory:
        factory_code = require_factory_access(current, factory)
        source_types = ("standard", "usluga") if factory_code == "ECO" else ("standard",)
        qry = qry.filter(
            ProductionOrder.source_type.in_(source_types),
            production_order_factory_condition(factory_code),
        )
    else:
        qry = qry.filter(ProductionOrder.source_type == "standard")
    pos = qry.options(
        selectinload(ProductionOrder.work_orders),
    ).order_by(ProductionOrder.id.desc()).all()

    rows_html = ""
    for po in pos:
        model = db.get(Model, po.model_id)
        so = db.get(SalesOrder, po.sales_order_id) if po.sales_order_id else None
        cust = db.get(Customer, so.customer_id) if so and so.customer_id else None
        model_image_url = model_display_image_url(model)
        model_image = (
            f"<img class='model-img' src='{_h(model_image_url)}' alt='{_h(model.name if model else po.model_id)}'>"
            if model_image_url
            else "<div class='model-img model-img-empty'>No image</div>"
        )
        stages = " &middot; ".join(
            f"{_h(w.operation)}[{_h(w.status)}] {_h(w.passed_qty)}/{_h(w.planned_output_qty)}"
            for w in sorted(po.work_orders, key=lambda x: x.id)
        ) or "&mdash;"
        dl = _h(po.deadline.strftime("%Y-%m-%d") if po.deadline else "")
        sales_order_no = so.order_no if so else ""
        rows_html += f"""
          <tr>
            <td><b>{_h(po.production_no)}</b></td>
            <td>{_h(sales_order_no) or '&mdash;'}</td>
            <td>{_h(cust.name if cust else po.service_customer_name or '')}</td>
            <td><div class='model-cell'>{model_image}<div>{_h(model.code if model else po.model_id)}<br><span class='sub'>{_h(model.name if model else '')}</span></div></div></td>
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
  .model-cell{{display:flex;gap:3mm;align-items:flex-start}}
  .model-img{{width:18mm;height:18mm;object-fit:cover;border:1px solid #cbd5e1;border-radius:2mm;background:#f8fafc;flex:0 0 auto}}
  .model-img-empty{{display:flex;align-items:center;justify-content:center;color:#64748b;font-size:7pt;text-align:center}}
  @media print {{ button{{display:none}} }}
</style></head>
<body>
  <h1>Milana ERP — Process Tracking</h1>
  <div class='sub'>Generated {now}</div>
  <table>
    <thead><tr>
      <th>Production No</th><th>Sales Order No</th><th>Customer</th><th>Model</th><th>Qty</th>
      <th>Status</th><th>Deadline</th><th>Stages</th>
    </tr></thead>
    <tbody>{rows_html or '<tr><td colspan=8>No active production orders.</td></tr>'}</tbody>
  </table>
  <button onclick="window.print()" style="margin-top:6mm;padding:3mm 8mm;background:#1d4ed8;color:#fff;border:none;border-radius:2mm">Print / Save as PDF</button>
</body></html>"""
    return HTMLResponse(content=html)
