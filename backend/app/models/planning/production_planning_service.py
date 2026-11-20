"""Production orders that planning opens for client and branded work.

Contract per operation:
* input: the validated `ProductionOrderIn` payload and the acting user
* output: the created `ProductionOrder` row
* refusals: 400 for a mismatched production type, an unconfirmed sales order or
  a closed branded planning order, 404 for a missing sales order or branded
  planning order
* records: one `production_orders` row with its batches and work orders, the
  sales order status move for client work and one `ProductionOrder` audit row
* transaction owner: both operations
* production internals stay in `app.models.production_service`; this module only
  orchestrates the public production operations.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.planning.branded_planning_order_input import BrandedPlanningOrderIn
from app.libs.dto.planning.branded_production_input import BrandedOrderWithProductionIn
from app.libs.dto.planning.branded_planning_order_output import BrandedPlanningOrderOut
from app.libs.dto.production.production import ProductionOrderIn
from app.libs.enums.planning import BrandedPlanningOrderStatus
from app.models.production.eco_fabric_source_service import resolve_eco_fabric_sources, planning_eco_balances
from app.models.audit_service import log_action
from app.models.planning.branded_orders_service import list_branded_orders, open_branded_order
from app.models.production_service import (
    create_production_batches,
    create_production_order,
    create_work_orders,
    printing_attachments_for_storage,
)
from app.schemas import BrandedPlanningOrder, SalesOrder, User


CLIENT_ORDER_STATUSES = {"confirmed", "pending_sales_approval", "planning_approved"}


def _planning_fabric_sources(db: Session, payload: ProductionOrderIn, current: User):
    materials = [row.model_dump() for row in payload.materials]
    primary = ({"eco_material_batch_id": payload.eco_fabric_batch_id} if payload.eco_fabric_batch_id
               else {"stock_batch_id": payload.fabric_batch_id})
    # The existing production operation makes its first material authoritative.
    # Do not assign an unused primary receipt's identity as an incidental write.
    rows = materials or ([primary] if any(primary.values()) else [])
    resolved = resolve_eco_fabric_sources(db, rows, current, cutting_code=payload.cutting_department_code, planning=True)
    fabric_batch_id = resolved[0]["stock_batch_id"] if resolved else None
    materials = resolved if materials else []
    ids = {row["stock_batch_id"] for row in materials} | ({fabric_batch_id} if fabric_batch_id else set())
    available = planning_eco_balances(db, ids, current, payload.cutting_department_code)
    return fabric_batch_id, materials, available


def create_client_order_production(db: Session, payload: ProductionOrderIn, current: User):
    """Open a production order for a confirmed client sales order."""
    if payload.production_type != "client_order":
        raise HTTPException(400, "Use /planning/create-branded-production for branded_stock")
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.status not in CLIENT_ORDER_STATUSES:
        raise HTTPException(400, f"Sales order must be confirmed before creating production (current: '{so.status}')")
    fabric_batch_id, materials, eco_available = _planning_fabric_sources(db, payload, current)
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type="client_order",
        model_id=payload.model_id,
        brand_id=payload.brand_id,
        fabric_batch_id=fabric_batch_id,
        sales_order_id=payload.sales_order_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        estimated_material_code=payload.estimated_material_code,
        estimated_material_amount=payload.estimated_material_amount,
        estimated_material_unit=payload.estimated_material_unit,
        materials=materials,
        eco_fabric_available=eco_available,
        printing_instructions=payload.printing_instructions,
        printing_attachments=printing_attachments,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    if payload.batches:
        create_production_batches(db, po.id, [b.model_dump() for b in payload.batches])
    include_printing = (
        any(bool(i.printing_required) for i in (so.items or []))
        or any(bool(i.printing_required) for i in payload.items)
        or bool(str(payload.printing_instructions or "").strip())
        or bool(printing_attachments)
    )
    create_work_orders(
        db,
        po.id,
        include_printing=include_printing,
        cutting_department_code=payload.cutting_department_code,
        sewing_factory_code=payload.sewing_factory_code,
    )
    so.status = "planning"
    log_action(db, current, "create", "ProductionOrder", po.id, new_value={"production_no": po.production_no})
    db.commit(); db.refresh(po)
    return po


def create_branded_order(db: Session, payload: BrandedOrderWithProductionIn, current: User) -> BrandedPlanningOrderOut:
    if payload.production is None or payload.production.planning_order_id is not None:
        raise HTTPException(409, "Select a model with a Qolip number and file to create a BSO.")
    order = BrandedPlanningOrderIn(
        ordered_for_type=payload.ordered_for_type, customer_id=payload.customer_id, notes=payload.notes,
    )
    production = create_branded_stock_production(db, payload.production, current, branded_order=order)
    return list_branded_orders(db, None, order_id=production.planning_order_id)[0]


def create_branded_stock_production(db: Session, payload: ProductionOrderIn, current: User, *,
                                    branded_order: BrandedPlanningOrderIn | None = None):
    """Open branded production and its planning order in one transaction."""
    if payload.production_type != "branded_stock":
        raise HTTPException(400, "production_type must be branded_stock")
    if payload.planning_order_id is not None and branded_order is not None:
        raise HTTPException(400, "Choose either an existing or a new BSO")
    planning_order = db.get(BrandedPlanningOrder, payload.planning_order_id) if payload.planning_order_id else None
    if payload.planning_order_id and not planning_order:
        raise HTTPException(404, "Branded planning order not found")
    if not planning_order:
        planning_order = open_branded_order(db, branded_order or BrandedPlanningOrderIn(), current)
    if planning_order.status != BrandedPlanningOrderStatus.OPEN.value:
        raise HTTPException(400, "Branded planning order is not open")
    fabric_batch_id, materials, eco_available = _planning_fabric_sources(db, payload, current)
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type="branded_stock",
        planning_order_id=planning_order.id,
        model_id=payload.model_id,
        brand_id=payload.brand_id,
        fabric_batch_id=fabric_batch_id,
        sales_order_id=None,
        collection_id=payload.collection_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        estimated_material_code=payload.estimated_material_code,
        estimated_material_amount=payload.estimated_material_amount,
        estimated_material_unit=payload.estimated_material_unit,
        materials=materials,
        eco_fabric_available=eco_available,
        printing_instructions=payload.printing_instructions,
        printing_attachments=printing_attachments,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=[i.model_dump() for i in payload.items],
        created_by=current.id,
    )
    if payload.batches:
        create_production_batches(db, po.id, [b.model_dump() for b in payload.batches])
    include_printing = (
        any(bool(i.printing_required) for i in payload.items)
        or bool(str(payload.printing_instructions or "").strip())
        or bool(printing_attachments)
    )
    create_work_orders(
        db,
        po.id,
        include_printing=include_printing,
        cutting_department_code=payload.cutting_department_code,
        sewing_factory_code=payload.sewing_factory_code,
    )
    log_action(
        db,
        current,
        "create",
        "ProductionOrder",
        po.id,
        new_value={
            "production_no": po.production_no,
            "type": "branded_stock",
            "planning_order_no": planning_order.order_no,
            "sewing_factory_code": payload.sewing_factory_code,
        },
    )
    db.commit(); db.refresh(po)
    return po
