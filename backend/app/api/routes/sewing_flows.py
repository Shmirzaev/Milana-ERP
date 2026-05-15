from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import SewingFlow, WorkOrder, User
from app.schemas.sewing_flow import (
    SewingFlowIn, SewingFlowUpdate, SewingFlowOut, SewingFlowWithLoad,
)
from app.schemas.production import WorkOrderOut
from app.services.audit import log_action

router = APIRouter(prefix="/sewing-flows", tags=["sewing-flows"])

_ACTIVE_WO_STATUSES = ("waiting", "ready", "in_progress", "paused")


def _bulk_load(db) -> dict[int, dict]:
    """Return {flow_id: {active_work_orders, planned_units, completed_units}}
    in a single grouped query — used by list_flows to avoid N+1."""
    rows = (
        db.query(
            WorkOrder.sewing_flow_id,
            func.count(WorkOrder.id),
            func.coalesce(func.sum(WorkOrder.planned_output_qty), 0),
            func.coalesce(func.sum(WorkOrder.passed_qty), 0),
        )
        .filter(WorkOrder.sewing_flow_id.isnot(None))
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .group_by(WorkOrder.sewing_flow_id)
        .all()
    )
    return {
        fid: {
            "active_work_orders": int(cnt or 0),
            "planned_units": int(planned or 0),
            "completed_units": int(done or 0),
        }
        for fid, cnt, planned, done in rows
    }


def _single_load(db, flow_id: int) -> dict:
    cnt, planned, done = (
        db.query(
            func.count(WorkOrder.id),
            func.coalesce(func.sum(WorkOrder.planned_output_qty), 0),
            func.coalesce(func.sum(WorkOrder.passed_qty), 0),
        )
        .filter(WorkOrder.sewing_flow_id == flow_id)
        .filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
        .one()
    )
    return {
        "active_work_orders": int(cnt or 0),
        "planned_units": int(planned or 0),
        "completed_units": int(done or 0),
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
    qry = db.query(WorkOrder).filter(WorkOrder.sewing_flow_id == fid)
    if only_active:
        qry = qry.filter(WorkOrder.status.in_(_ACTIVE_WO_STATUSES))
    return qry.order_by(WorkOrder.id.desc()).all()
