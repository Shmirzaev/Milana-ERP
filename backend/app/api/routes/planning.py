from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, require_permissions
from app.models import User, SalesOrder
from app.schemas.production import (
    MaterialRequirement,
    PlanningEstimateSubmitIn,
    PlanningEstimateOut,
    ProductionOrderIn,
    ProductionOrderOut,
)
from app.services.planning import material_requirements_for_sales_order, planning_estimate_for_sales_order
from app.services.production import create_production_order, create_work_orders
from app.services.audit import log_action
from app.services.workflow import notify_department

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/material-requirements/{sales_order_id}", response_model=list[MaterialRequirement])
def get_material_requirements(sales_order_id: int, db: DbSession, _: User = Depends(require_permissions("planning.requirements", "*"))):
    rows = material_requirements_for_sales_order(db, sales_order_id)
    return [MaterialRequirement(**r) for r in rows]


@router.get("/estimate/{sales_order_id}", response_model=PlanningEstimateOut)
def get_planning_estimate_preview(
    sales_order_id: int,
    db: DbSession,
    _: User = Depends(require_permissions("planning.requirements", "planning.production", "sales.orders", "*")),
):
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.order_type != "client_order":
        raise HTTPException(400, "Planning estimate flow is only for client_order")

    estimate = planning_estimate_for_sales_order(db, sales_order_id)
    if not estimate:
        raise HTTPException(404, "Sales order not found")

    if so.planning_estimated_material_cost is not None:
        estimate["estimated_material_cost"] = float(so.planning_estimated_material_cost)
    estimate["estimated_labor_cost"] = float(so.planning_estimated_labor_cost or 0)
    estimate["estimated_electricity_cost"] = float(so.planning_estimated_electricity_cost or 0)
    estimate["estimated_other_expenses"] = float(so.planning_estimated_other_cost or 0)
    estimated_net_cost = (
        estimate["estimated_material_cost"]
        + estimate["estimated_labor_cost"]
        + estimate["estimated_electricity_cost"]
        + estimate["estimated_other_expenses"]
    )
    estimate["estimated_net_cost"] = float(so.planning_estimated_net_cost or estimated_net_cost)
    estimate["suggested_price_15"] = float(so.planning_suggested_price_15 or round(estimate["estimated_net_cost"] * 1.15, 2))
    estimate["suggested_price_20"] = float(so.planning_suggested_price_20 or round(estimate["estimated_net_cost"] * 1.20, 2))
    if so.planning_estimated_lead_time_minutes is not None:
        lead_minutes = int(so.planning_estimated_lead_time_minutes)
        estimate["estimated_lead_time_minutes"] = lead_minutes
        estimate["estimated_lead_time_hours"] = round(lead_minutes / 60.0, 2)
    return PlanningEstimateOut(status=so.status, **estimate)


@router.post("/submit-estimate/{sales_order_id}", response_model=PlanningEstimateOut)
def submit_planning_estimate(
    sales_order_id: int,
    db: DbSession,
    payload: PlanningEstimateSubmitIn | None = None,
    current: User = Depends(require_permissions("planning.requirements", "planning.production", "*")),
):
    so = db.get(SalesOrder, sales_order_id)
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.order_type != "client_order":
        raise HTTPException(400, "Planning estimate approval flow is only for client_order")
    if so.status not in ("confirmed", "pending_sales_approval"):
        raise HTTPException(400, f"Cannot submit estimate for sales order in status '{so.status}'")

    estimate = planning_estimate_for_sales_order(db, sales_order_id)
    if not estimate:
        raise HTTPException(404, "Sales order not found")

    est_material_cost = float(
        payload.estimated_material_cost
        if payload and payload.estimated_material_cost is not None
        else estimate["estimated_material_cost"]
    )
    est_labor_cost = float(
        payload.estimated_labor_cost
        if payload and payload.estimated_labor_cost is not None
        else estimate["estimated_labor_cost"]
    )
    est_electricity_cost = float(
        payload.estimated_electricity_cost
        if payload and payload.estimated_electricity_cost is not None
        else estimate["estimated_electricity_cost"]
    )
    est_other_expenses = float(
        payload.estimated_other_expenses
        if payload and payload.estimated_other_expenses is not None
        else estimate["estimated_other_expenses"]
    )
    est_lead_minutes = int(
        payload.estimated_lead_time_minutes
        if payload and payload.estimated_lead_time_minutes is not None
        else estimate["estimated_lead_time_minutes"]
    )
    est_lead_hours = round(est_lead_minutes / 60.0, 2)
    est_net_cost = round(est_material_cost + est_labor_cost + est_electricity_cost + est_other_expenses, 2)
    suggested_15 = round(est_net_cost * 1.15, 2)
    suggested_20 = round(est_net_cost * 1.20, 2)

    estimate["estimated_material_cost"] = est_material_cost
    estimate["estimated_labor_cost"] = est_labor_cost
    estimate["estimated_electricity_cost"] = est_electricity_cost
    estimate["estimated_other_expenses"] = est_other_expenses
    estimate["estimated_net_cost"] = est_net_cost
    estimate["suggested_price_15"] = suggested_15
    estimate["suggested_price_20"] = suggested_20
    estimate["estimated_lead_time_minutes"] = est_lead_minutes
    estimate["estimated_lead_time_hours"] = est_lead_hours

    so.planning_estimated_material_cost = est_material_cost
    so.planning_estimated_labor_cost = est_labor_cost
    so.planning_estimated_electricity_cost = est_electricity_cost
    so.planning_estimated_other_cost = est_other_expenses
    so.planning_estimated_net_cost = est_net_cost
    so.planning_suggested_price_15 = suggested_15
    so.planning_suggested_price_20 = suggested_20
    so.planning_estimated_lead_time_minutes = est_lead_minutes
    so.planning_estimate_comment = payload.estimate_comment.strip() if payload and payload.estimate_comment else None
    so.planning_estimate_submitted_at = datetime.now(timezone.utc)
    so.planning_estimate_submitted_by = current.id
    if payload and payload.planned_deadline is not None:
        so.deadline = payload.planned_deadline
    so.status = "pending_sales_approval"
    summary = (
        f"[Planning estimate] Material cost: {estimate['estimated_material_cost']:.2f}; "
        f"Labor: {estimate['estimated_labor_cost']:.2f}; "
        f"Electricity: {estimate['estimated_electricity_cost']:.2f}; "
        f"Other: {estimate['estimated_other_expenses']:.2f}; "
        f"Net: {estimate['estimated_net_cost']:.2f}; "
        f"+15%: {estimate['suggested_price_15']:.2f}; "
        f"+20%: {estimate['suggested_price_20']:.2f}; "
        f"Lead time: {estimate['estimated_lead_time_hours']:.2f}h "
        f"({estimate['estimated_lead_time_minutes']} min); Qty: {estimate['total_quantity']}"
    )
    if so.deadline:
        summary += f"; Deadline: {so.deadline.isoformat()}"
    if so.planning_estimate_comment:
        summary += f"; Comment: {so.planning_estimate_comment}"
    so.notes = f"{so.notes}\n{summary}".strip() if so.notes else summary

    notify_department(
        db,
        department_code="SLS",
        title=f"Planning estimate ready for {so.order_no}",
        message="Review material usage, estimated cost, and estimated lead time, then approve.",
        link=f"/sales-orders/{so.id}",
        exclude_user_id=current.id,
    )
    log_action(
        db,
        current,
        "submit_estimate",
        "SalesOrder",
        so.id,
        new_value={
            "estimated_material_cost": estimate["estimated_material_cost"],
            "estimated_labor_cost": estimate["estimated_labor_cost"],
            "estimated_electricity_cost": estimate["estimated_electricity_cost"],
            "estimated_other_expenses": estimate["estimated_other_expenses"],
            "estimated_net_cost": estimate["estimated_net_cost"],
            "suggested_price_15": estimate["suggested_price_15"],
            "suggested_price_20": estimate["suggested_price_20"],
            "estimated_lead_time_minutes": estimate["estimated_lead_time_minutes"],
            "total_quantity": estimate["total_quantity"],
        },
    )
    db.commit()
    return PlanningEstimateOut(status=so.status, **estimate)


@router.post("/create-production-order", response_model=ProductionOrderOut, status_code=201)
def create_for_client_order(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    if payload.production_type != "client_order":
        raise HTTPException(400, "Use /planning/create-branded-production for branded_stock")
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.status != "planning_approved":
        raise HTTPException(400, f"Sales order must be 'planning_approved' before creating PO (current: '{so.status}')")
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
    include_printing = any(bool(i.printing_required) for i in (so.items or [])) if so else False
    create_work_orders(db, po.id, include_printing=include_printing)
    so.status = "planning"
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
