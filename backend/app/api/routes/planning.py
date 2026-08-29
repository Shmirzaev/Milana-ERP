from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import joinedload, selectinload

from app.core.deps import DbSession, require_permissions
from app.models import BrandedPlanningOrder, Customer, Model, User, SalesOrder
from app.schemas.production import (
    BrandedPlanningOrderIn,
    MaterialRequirement,
    ProductionOrderIn,
    ProductionOrderOut,
)
from app.services.planning import material_requirements_for_sales_order
from app.services.production import (
    create_production_order,
    create_production_batches,
    create_work_orders,
    printing_attachments_for_storage,
)
from app.services.audit import log_action
from app.services.model_images import material_preview_image_url, model_display_image_url
from app.services.numbering import next_branded_planning_order_no

router = APIRouter(prefix="/planning", tags=["planning"])

BRANDED_ORDER_PARTIES = {
    "milana": "Milana",
    "eco_cotton": "Eco Cotton",
    "besttex": "Besttex",
}


def _branded_model_fabric_label(model: Model) -> str | None:
    for row in sorted(model.bom or [], key=lambda value: int(value.id or 0)):
        item = getattr(row, "item", None)
        if str(getattr(item, "category", "") or "").lower() not in {"fabric", "semi_finished"}:
            continue
        item_label = str(getattr(item, "name", None) or getattr(item, "sku", None) or "").strip()
        color = str(row.color or "").strip()
        label = " / ".join(value for value in (item_label, color) if value)
        if label:
            return label

    details = model.details_json if isinstance(model.details_json, dict) else {}
    general = details.get("general") if isinstance(details.get("general"), dict) else {}
    return str(general.get("variant_fabric") or general.get("variantFabric") or "").strip() or None


def _branded_model_payload(model: Model) -> dict:
    return {
        "id": model.id,
        "code": model.code,
        "name": model.name,
        "primary_image_url": model_display_image_url(model),
        "variant_fabric": _branded_model_fabric_label(model),
        "fabric_image_url": material_preview_image_url(model),
    }


def _branded_order_payload(
    order: BrandedPlanningOrder,
    model_by_id: dict[int, dict] | None = None,
) -> dict:
    model_by_id = model_by_id or {}
    productions = sorted(order.production_orders or [], key=lambda row: int(row.id))
    return {
        "id": order.id,
        "order_no": order.order_no,
        "ordered_for_type": order.ordered_for_type,
        "customer_id": order.customer_id,
        "ordered_for_name": order.ordered_for_name,
        "status": order.status,
        "notes": order.notes,
        "created_by": order.created_by,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "production_count": len(productions),
        "total_quantity": sum(int(row.planned_quantity or 0) for row in productions),
        "productions": [
            {
                "id": row.id,
                "order_no": row.order_no,
                "production_no": row.production_no,
                "model_id": row.model_id,
                "model": model_by_id.get(int(row.model_id)),
                "planned_quantity": row.planned_quantity,
                "status": row.status,
            }
            for row in productions
        ],
    }


@router.get("/branded-order-parties")
def branded_order_parties(
    db: DbSession,
    _: User = Depends(require_permissions("planning.production", "*")),
):
    customers = db.query(Customer).order_by(Customer.name.asc()).all()
    return {
        "companies": [{"type": key, "name": name} for key, name in BRANDED_ORDER_PARTIES.items()],
        "customers": [{"id": row.id, "name": row.name} for row in customers],
    }


@router.get("/branded-orders")
def list_branded_orders(
    db: DbSession,
    _: User = Depends(require_permissions("planning.production", "*")),
    status: str | None = "open",
):
    query = db.query(BrandedPlanningOrder).options(joinedload(BrandedPlanningOrder.production_orders))
    if status:
        query = query.filter(BrandedPlanningOrder.status == status)
    rows = query.order_by(BrandedPlanningOrder.id.desc()).all()
    model_ids = {
        int(production.model_id)
        for order in rows
        for production in (order.production_orders or [])
        if production.model_id
    }
    models = (
        db.query(Model)
        .options(selectinload(Model.images), selectinload(Model.bom))
        .filter(Model.id.in_(model_ids))
        .all()
        if model_ids
        else []
    )
    model_by_id = {int(model.id): _branded_model_payload(model) for model in models}
    return [_branded_order_payload(row, model_by_id) for row in rows]


@router.post("/branded-orders", status_code=201)
def create_branded_order(
    payload: BrandedPlanningOrderIn,
    db: DbSession,
    current: User = Depends(require_permissions("planning.production", "*")),
):
    ordered_for_type = str(payload.ordered_for_type or "").strip().lower()
    customer_id = payload.customer_id
    if ordered_for_type == "customer":
        customer = db.get(Customer, customer_id) if customer_id else None
        if not customer:
            raise HTTPException(404, "Customer not found")
        ordered_for_name = customer.name
    elif ordered_for_type in BRANDED_ORDER_PARTIES:
        customer_id = None
        ordered_for_name = BRANDED_ORDER_PARTIES[ordered_for_type]
    else:
        raise HTTPException(400, "Choose Milana, Eco Cotton, Besttex, or a customer")

    order = BrandedPlanningOrder(
        order_no=next_branded_planning_order_no(db),
        ordered_for_type=ordered_for_type,
        customer_id=customer_id,
        ordered_for_name=ordered_for_name,
        status="open",
        notes=str(payload.notes or "").strip() or None,
        created_by=current.id,
    )
    db.add(order)
    db.flush()
    log_action(
        db, current, "create", "BrandedPlanningOrder", order.id,
        new_value={"order_no": order.order_no, "ordered_for": order.ordered_for_name},
    )
    db.commit()
    db.refresh(order)
    return _branded_order_payload(order)


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
    if payload.production_type != "client_order":
        raise HTTPException(400, "Use /planning/create-branded-production for branded_stock")
    so = db.get(SalesOrder, payload.sales_order_id) if payload.sales_order_id else None
    if not so:
        raise HTTPException(404, "Sales order not found")
    allowed_statuses = {"confirmed", "pending_sales_approval", "planning_approved"}
    if so.status not in allowed_statuses:
        raise HTTPException(400, f"Sales order must be confirmed before creating production (current: '{so.status}')")
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type="client_order",
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
        materials=[row.model_dump() for row in payload.materials],
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


@router.post("/create-branded-production", response_model=ProductionOrderOut, status_code=201)
def create_for_branded(payload: ProductionOrderIn, db: DbSession, current: User = Depends(require_permissions("planning.production", "*"))):
    if payload.production_type != "branded_stock":
        raise HTTPException(400, "production_type must be branded_stock")
    planning_order = db.get(BrandedPlanningOrder, payload.planning_order_id) if payload.planning_order_id else None
    if payload.planning_order_id and not planning_order:
        raise HTTPException(404, "Branded planning order not found")
    if not planning_order:
        planning_order = BrandedPlanningOrder(
            order_no=next_branded_planning_order_no(db),
            ordered_for_type="milana",
            ordered_for_name=BRANDED_ORDER_PARTIES["milana"],
            status="open",
            created_by=current.id,
        )
        db.add(planning_order)
        db.flush()
    if planning_order.status != "open":
        raise HTTPException(400, "Branded planning order is not open")
    printing_attachments = printing_attachments_for_storage(payload.printing_attachments)
    po = create_production_order(
        db,
        production_type="branded_stock",
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
        materials=[row.model_dump() for row in payload.materials],
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
        db, current, "create", "ProductionOrder", po.id,
        new_value={
            "production_no": po.production_no,
            "type": "branded_stock",
            "planning_order_no": planning_order.order_no,
            "sewing_factory_code": payload.sewing_factory_code,
        },
    )
    db.commit(); db.refresh(po)
    return po
