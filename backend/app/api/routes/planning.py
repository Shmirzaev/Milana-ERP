from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.deps import DbSession, require_permissions
from app.libs.dto.planning.branded_planning_order_input import BrandedPlanningOrderIn
from app.libs.dto.planning.material_requirement_output import MaterialRequirement
from app.libs.dto.production.production import ProductionOrderIn, ProductionOrderOut
from app.models.planning import branded_orders_service, production_planning_service
from app.models.planning_service import material_requirements_for_sales_order
from app.schemas import User

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/branded-orders/{order_id}/export.xlsx")
def export_branded_order(order_id: int, db: DbSession,
                         _: User = Depends(require_permissions("planning.production", "*"))):
    workbook = branded_orders_service.export_branded_order_workbook(db, order_id)
    return Response(workbook,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="branded-order-{order_id}.xlsx"'})


@router.get("/branded-order-parties")
def branded_order_parties(
    db: DbSession,
    _: User = Depends(require_permissions("planning.production", "*")),
):
    return branded_orders_service.branded_order_parties(db)


@router.get("/branded-orders")
def list_branded_orders(
    db: DbSession,
    _: User = Depends(require_permissions("planning.production", "*")),
    status: str | None = "open",
):
    return branded_orders_service.list_branded_orders(db, status)


@router.get("/branded-order-customers")
def branded_order_customers(db: DbSession,
                           _: User = Depends(require_permissions("planning.production", "*")),
                           q: str = Query("", max_length=100)):
    return branded_orders_service.branded_order_customers(db, q)


@router.post("/branded-orders", status_code=201)
def create_branded_order(
    payload: BrandedPlanningOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("planning.production", "*")),
):
    return branded_orders_service.create_branded_order(db, payload, current)


@router.get("/material-requirements/{sales_order_id}", response_model=list[MaterialRequirement])
def get_material_requirements(
    sales_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions("planning.requirements", "sales.orders", "*")),
):
    rows = material_requirements_for_sales_order(db, sales_order_id)
    return [MaterialRequirement(**r) for r in rows]


@router.post("/create-production-order", response_model=ProductionOrderOut, status_code=201)
def create_for_client_order(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    return production_planning_service.create_client_order_production(db, payload, current)


@router.post("/create-branded-production", response_model=ProductionOrderOut, status_code=201)
def create_for_branded(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    return production_planning_service.create_branded_stock_production(db, payload, current)
