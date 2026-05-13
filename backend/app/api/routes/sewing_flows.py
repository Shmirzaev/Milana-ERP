from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import SewingFlow, WorkOrder, ProductionOrder, User
from app.schemas.sewing_flow import (
    SewingFlowIn, SewingFlowUpdate, SewingFlowOut, SewingFlowWithLoad,
)
from app.schemas.production import WorkOrderOut
from app.services.audit import log_action

router = APIRouter(prefix="/sewing-flows", tags=["sewing-flows"])


def _load_for(db, flow_id: int) -> dict:
    """Aggregate active work-order count + planned/completed units for a flow."""
    rows = db.query(WorkOrder).filter(
        WorkOrder.sewing_flow_id == flow_id,
        WorkOrder.status.in_(["waiting", "ready", "in_progress", "paused"]),
    ).all()
    return {
        "active_work_orders": len(rows),
        "planned_units": sum(w.planned_output_qty or 0 for w in rows),
        "completed_units": sum(w.passed_qty or 0 for w in rows),
    }


@router.get("", response_model=list[SewingFlowWithLoad])
def list_flows(db: DbSession, _: CurrentUser, only_active: bool = True):
    qry = db.query(SewingFlow)
    if only_active:
        qry = qry.filter(SewingFlow.is_active.is_(True))
    flows = qry.order_by(SewingFlow.code).all()
    return [
        SewingFlowWithLoad(
            id=f.id, name=f.name, code=f.code, description=f.description,
            capacity_per_day=f.capacity_per_day, supervisor_id=f.supervisor_id,
            is_active=f.is_active,
            **_load_for(db, f.id),
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
        **_load_for(db, f.id),
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
        qry = qry.filter(WorkOrder.status.in_(["waiting", "ready", "in_progress", "paused"]))
    return qry.order_by(WorkOrder.id.desc()).all()
