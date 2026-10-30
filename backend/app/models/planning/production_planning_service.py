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

from app.libs.dto.production.production import ProductionOrderIn
from app.libs.enums.planning import BrandedPlanningOrderStatus, BrandedPlanningOrderType
from app.libs.enums.production import ProductionType
from app.models.audit_service import log_action
from app.models.numbering_service import next_branded_planning_order_no
from app.models.planning.branded_orders_service import BRANDED_ORDER_PARTIES
from app.models.production_service import (
    create_production_batches,
    create_production_order,
    create_work_orders,
    printing_attachments_for_storage,
)
from app.schemas import BrandedPlanningOrder, SalesOrder, User
from app.schemas.planning.branded_order_persistence import (
    BrandedPlanningOrderInsert,
    insert_branded_planning_order,
)


CLIENT_ORDER_STATUSES = {"confirmed", "pending_sales_approval", "planning_approved"}


def create_client_order_production(db: Session, payload: ProductionOrderIn, current: User):
    """Open a production order for a confirmed client sales order."""
    if payload.production_type is not ProductionType.CLIENT_ORDER:
        raise HTTPException(400, "Use /planning/create-branded-production for branded_stock")
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if not so:
        raise HTTPException(404, "Sales order not found")
    if so.status not in CLIENT_ORDER_STATUSES:
        raise HTTPException(400, f"Sales order must be confirmed before creating production (current: '{so.status}')")
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type=ProductionType.CLIENT_ORDER,
        model_id=payload.model_id,
        brand_id=payload.brand_id,
        fabric_batch_id=payload.fabric_batch_id,
        sales_order_id=payload.sales_order_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        estimated_material_code=payload.estimated_material_code,
        estimated_material_amount=payload.estimated_material_amount,
        estimated_material_unit=payload.estimated_material_unit,
        materials=payload.materials,
        printing_instructions=payload.printing_instructions,
        printing_attachments=printing_attachments,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=payload.items,
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


def create_branded_stock_production(db: Session, payload: ProductionOrderIn, current: User):
    """Open a production order for branded stock on an open branded planning order."""
    if payload.production_type is not ProductionType.BRANDED_STOCK:
        raise HTTPException(400, "production_type must be branded_stock")
    planning_order = db.get(BrandedPlanningOrder, payload.planning_order_id) if payload.planning_order_id else None
    if payload.planning_order_id and not planning_order:
        raise HTTPException(404, "Branded planning order not found")
    if not planning_order:
        planning_order = insert_branded_planning_order(
            db,
            BrandedPlanningOrderInsert(
                order_no=next_branded_planning_order_no(db),
                ordered_for_type=BrandedPlanningOrderType.MILANA,
                customer_id=None,
                ordered_for_name=BRANDED_ORDER_PARTIES[BrandedPlanningOrderType.MILANA],
                status=BrandedPlanningOrderStatus.OPEN,
                notes=None,
                created_by=current.id,
            ),
        )
    if planning_order.status != BrandedPlanningOrderStatus.OPEN.value:
        raise HTTPException(400, "Branded planning order is not open")
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type=ProductionType.BRANDED_STOCK,
        planning_order_id=planning_order.id,
        model_id=payload.model_id,
        brand_id=payload.brand_id,
        fabric_batch_id=payload.fabric_batch_id,
        sales_order_id=None,
        collection_id=payload.collection_id,
        planned_quantity=payload.planned_quantity,
        start_date=payload.start_date,
        deadline=payload.deadline,
        estimated_material_code=payload.estimated_material_code,
        estimated_material_amount=payload.estimated_material_amount,
        estimated_material_unit=payload.estimated_material_unit,
        materials=payload.materials,
        printing_instructions=payload.printing_instructions,
        printing_attachments=printing_attachments,
        destination_warehouse_id=payload.destination_warehouse_id,
        items=payload.items,
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
