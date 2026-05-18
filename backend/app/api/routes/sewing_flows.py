from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import SewingFlow, WorkOrder, User, SewingAssignment
from app.schemas.sewing_flow import (
    SewingFlowIn, SewingFlowUpdate, SewingFlowOut, SewingFlowWithLoad,
)
from app.schemas.production import WorkOrderOut
from app.services.audit import log_action

router = APIRouter(prefix="/sewing-flows", tags=["sewing-flows"])

_ACTIVE_WO_STATUSES = ("waiting", "ready", "in_progress", "paused")
_ACTIVE_ASSIGN_STATUSES = ("planned", "in_progress")
_ASSIGNMENT_MANAGED_STATUSES = ("planned", "in_progress", "completed")


def _bulk_load(db) -> dict[int, dict]:
    """Return {flow_id: {active_work_orders, planned_units, completed_units}}
    in a single grouped query — used by list_flows to avoid N+1."""
    rows = (
        db.query(
            WorkOrder.sewing_flow_id,
            WorkOrder.id,
            WorkOrder.planned_output_qty,
            WorkOrder.passed_qty,
        )
        .filter(WorkOrder.sewing_flow_id.isnot(None))
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .all()
    )
    assignment_managed_wo_ids = {
        wid for (wid,) in db.query(SewingAssignment.work_order_id).filter(
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).distinct().all()
    }
    direct_by_flow: dict[int, dict] = {}
    for fid, wid, planned, done in rows:
        if not fid or wid in assignment_managed_wo_ids:
            continue
        bucket = direct_by_flow.setdefault(int(fid), {"active_work_orders": 0, "planned_units": 0, "completed_units": 0})
        bucket["active_work_orders"] += 1
        bucket["planned_units"] += int(planned or 0)
        bucket["completed_units"] += int(done or 0)

    split_rows = (
        db.query(
            SewingAssignment.sewing_flow_id,
            func.count(func.distinct(SewingAssignment.work_order_id)),
            func.coalesce(func.sum(SewingAssignment.quantity), 0),
            func.coalesce(func.sum(SewingAssignment.completed_qty), 0),
        )
        .filter(SewingAssignment.status.in_(_ACTIVE_ASSIGN_STATUSES))
        .group_by(SewingAssignment.sewing_flow_id)
        .all()
    )
    split_by_flow = {
        int(fid): {
            "active_work_orders": int(cnt or 0),
            "planned_units": int(planned or 0),
            "completed_units": int(done or 0),
        }
        for fid, cnt, planned, done in split_rows
    }

    out: dict[int, dict] = {}
    for fid, vals in direct_by_flow.items():
        out[fid] = dict(vals)
    for fid, vals in split_by_flow.items():
        cur = out.setdefault(fid, {"active_work_orders": 0, "planned_units": 0, "completed_units": 0})
        cur["active_work_orders"] += vals["active_work_orders"]
        cur["planned_units"] += vals["planned_units"]
        cur["completed_units"] += vals["completed_units"]
    return out


def _single_load(db, flow_id: int) -> dict:
    assignment_managed_wo_ids = {
        wid for (wid,) in db.query(SewingAssignment.work_order_id).filter(
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).distinct().all()
    }
    direct_rows = (
        db.query(WorkOrder.id, WorkOrder.planned_output_qty, WorkOrder.passed_qty)
        .filter(WorkOrder.sewing_flow_id == flow_id)
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .all()
    )
    direct_active = 0
    direct_planned = 0
    direct_done = 0
    for wid, planned, done in direct_rows:
        if wid in assignment_managed_wo_ids:
            continue
        direct_active += 1
        direct_planned += int(planned or 0)
        direct_done += int(done or 0)

    split_cnt, split_planned, split_done = (
        db.query(
            func.count(func.distinct(SewingAssignment.work_order_id)),
            func.coalesce(func.sum(SewingAssignment.quantity), 0),
            func.coalesce(func.sum(SewingAssignment.completed_qty), 0),
        )
        .filter(SewingAssignment.sewing_flow_id == flow_id)
        .filter(SewingAssignment.status.in_(_ACTIVE_ASSIGN_STATUSES))
        .one()
    )
    return {
        "active_work_orders": int(direct_active + int(split_cnt or 0)),
        "planned_units": int(direct_planned + int(split_planned or 0)),
        "completed_units": int(direct_done + int(split_done or 0)),
    }


@router.get("", response_model=list[SewingFlowWithLoad])
def list_flows(db: DbSession, _: CurrentUser, only_active: bool = True):
    qry = db.query(SewingFlow)
    if only_active:
        qry = qry.filter(SewingFlow.is_active.is_(True))
    flows = qry.order_by(SewingFlow.code).all()
    loads = _bulk_load(db)
    empty = {"active_work_orders": 0, "planned_units": 0, "completed_units": 0}
    return [
        SewingFlowWithLoad(
            id=f.id, name=f.name, code=f.code, description=f.description,
            capacity_per_day=f.capacity_per_day, supervisor_id=f.supervisor_id,
            is_active=f.is_active,
            **loads.get(f.id, empty),
        )
        for f in flows
    ]


@router.post("", response_model=SewingFlowOut, status_code=201)
def create_flow(payload: SewingFlowIn, db: DbSession, current: User = Depends(require_permissions("sewing.flows", "*"))):
    if db.query(SewingFlow).filter(SewingFlow.code == payload.code).first():
        raise HTTPException(400, "Flow code already exists")
    f = SewingFlow(**payload.model_dump())
    db.add(f); db.flush()
    log_action(db, current, "create", "SewingFlow", f.id, new_value={"code": f.code})
    db.commit(); db.refresh(f)
    return f


@router.get("/{fid}", response_model=SewingFlowWithLoad)
def get_flow(fid: int, db: DbSession, _: CurrentUser):
    f = db.get(SewingFlow, fid)
    if not f: raise HTTPException(404, "Sewing flow not found")
    return SewingFlowWithLoad(
        id=f.id, name=f.name, code=f.code, description=f.description,
        capacity_per_day=f.capacity_per_day, supervisor_id=f.supervisor_id,
        is_active=f.is_active,
        **_single_load(db, f.id),
    )


@router.patch("/{fid}", response_model=SewingFlowOut)
def update_flow(fid: int, payload: SewingFlowUpdate, db: DbSession, current: User = Depends(require_permissions("sewing.flows", "*"))):
    f = db.get(SewingFlow, fid)
    if not f: raise HTTPException(404, "Sewing flow not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(f, k, v)
    log_action(db, current, "update", "SewingFlow", f.id, new_value=changes)
    db.commit(); db.refresh(f)
    return f


@router.get("/{fid}/work-orders", response_model=list[WorkOrderOut])
def flow_work_orders(fid: int, db: DbSession, _: CurrentUser, only_active: bool = False):
    if not db.get(SewingFlow, fid):
        raise HTTPException(404, "Sewing flow not found")

    assignment_managed_wo_ids = {
        wid for (wid,) in db.query(SewingAssignment.work_order_id).filter(
            SewingAssignment.status.in_(_ASSIGNMENT_MANAGED_STATUSES),
        ).distinct().all()
    }

    direct_qry = db.query(WorkOrder).filter(WorkOrder.sewing_flow_id == fid)
    if only_active:
        direct_qry = direct_qry.filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
    direct = [w for w in direct_qry.all() if w.id not in assignment_managed_wo_ids]

    split_qry = (
        db.query(WorkOrder)
        .join(SewingAssignment, SewingAssignment.work_order_id == WorkOrder.id)
        .filter(SewingAssignment.sewing_flow_id == fid)
    )
    if only_active:
        split_qry = split_qry.filter(SewingAssignment.status.in_(_ACTIVE_ASSIGN_STATUSES))
    split = split_qry.all()

    uniq: dict[int, WorkOrder] = {w.id: w for w in direct}
    for w in split:
        uniq[w.id] = w
    return sorted(uniq.values(), key=lambda w: w.id, reverse=True)
