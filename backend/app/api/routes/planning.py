from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import User, SalesOrder
from app.schemas.production import ProductionOrderIn, ProductionOrderOut, MaterialRequirement
from app.services.planning import material_requirements_for_sales_order
from app.services.production import create_production_order, create_work_orders
from app.services.audit import log_action

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/material-requirements/{sales_order_id}", response_model=list[MaterialRequirement])
def get_material_requirements(sales_order_id: int, db: DbSession, _: User = Depends(require_permissions("planning.requirements", "*"))):
    rows = material_requirements_for_sales_order(db, sales_order_id)
    return [MaterialRequirement(**r) for r in rows]


@router.post("/create-production-order", response_model=ProductionOrderOut, status_code=201)
def create_for_client_order(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    if payload.production_type != "client_order":
        raise HTTPException(400, "Use /planning/create-branded-production for branded_stock")
    po = create_production_order(
        db,
        production_type="client_order",
        model_id=payload.model_id,
        sales_order_id=payload.sales_order_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    include_printing = any(bool(i.printing_required) for i in (so.items or [])) if so else False
    create_work_orders(db, po.id, include_printing=include_printing)
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no})
    db.commit(); db.refresh(po)
    return po


@router.post("/create-branded-production", response_model=ProductionOrderOut, status_code=201)
def create_for_branded(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    if payload.production_type != "branded_stock":
        raise HTTPException(400, "production_type must be branded_stock")
    po = create_production_order(
        db,
        production_type="branded_stock",
        model_id=payload.model_id,
        sales_order_id=None,
        collection_id=payload.collection_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    create_work_orders(db, po.id, include_printing=False)
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no, "type": "branded_stock"})
    db.commit(); db.refresh(po)
    return po
