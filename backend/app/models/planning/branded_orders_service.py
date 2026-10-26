"""Branded planning orders: list, parties, customers, creation and export.

Contract per operation:
* input: the acting user, the validated payload and the filter arguments
* output: the typed branded planning order payload (export returns the
  workbook bytes)
* refusals: 404 when the customer or the branded order does not exist, 400 when
  the ordered-for party is unknown
* records: one `branded_planning_orders` row and one `BrandedPlanningOrder`
  audit row on creation. The mapped row insert is schema-owned
  (`app.schemas.planning.branded_order_persistence`); this service decides the
  values and owns the transaction
* transaction owner: `create_branded_order`
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from app.libs.dto.planning.branded_planning_order_input import BrandedPlanningOrderIn
from app.libs.dto.planning.branded_planning_order_output import (
    BrandedCuttingDepartmentOut,
    BrandedModelOut,
    BrandedPlanningOrderOut,
    BrandedProductionOut,
)
from app.libs.enums.planning import (
    BrandedCuttingProgress,
    BrandedPlanningOrderStatus,
    BrandedPlanningOrderType,
)
from app.models.audit_service import log_action
from app.models.branded_order_export_service import build_branded_order_workbook
from app.models.model_images_service import material_preview_image_url, model_display_image_url
from app.models.numbering_service import next_branded_planning_order_no
from app.schemas import BrandedPlanningOrder, Customer, Department, Model, User, WorkOrder
from app.schemas.planning.branded_order_persistence import (
    BrandedPlanningOrderInsert,
    insert_branded_planning_order,
)


BRANDED_ORDER_PARTIES = {
    BrandedPlanningOrderType.MILANA: "Milana",
    BrandedPlanningOrderType.ECO_COTTON: "Eco Cotton",
    BrandedPlanningOrderType.BESTTEX: "Besttex",
}


def branded_model_fabric_label(model: Model) -> str | None:
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


def branded_model_payload(model: Model) -> dict:
    return {
        "id": model.id,
        "code": model.code,
        "name": model.name,
        "primary_image_url": model_display_image_url(model),
        "variant_fabric": branded_model_fabric_label(model),
        "fabric_image_url": material_preview_image_url(model),
    }


def branded_order_payload(
    order: BrandedPlanningOrder,
    model_by_id: dict[int, dict] | None = None,
    cutting_by_id: dict[int, BrandedCuttingProgress] | None = None,
    cutting_details_by_id: dict[int, dict] | None = None,
) -> BrandedPlanningOrderOut:
    """Return the branded planning order payload.

    The fixed vocabularies are converted to their canonical enum members at
    this boundary, so a stored plain string never leaves the service as an
    untyped value. The wire payload is unchanged.
    """
    model_by_id = model_by_id or {}
    cutting_by_id = cutting_by_id or {}
    cutting_details_by_id = cutting_details_by_id or {}
    productions = sorted(order.production_orders or [], key=lambda row: int(row.id))
    cutting_states = [
        cutting_by_id.get(row.id, BrandedCuttingProgress.NOT_STARTED) for row in productions
    ]
    return BrandedPlanningOrderOut(
        id=order.id,
        order_no=order.order_no,
        ordered_for_type=BrandedPlanningOrderType(order.ordered_for_type),
        customer_id=order.customer_id,
        ordered_for_name=order.ordered_for_name,
        status=BrandedPlanningOrderStatus(order.status),
        notes=order.notes,
        created_by=order.created_by,
        created_at=order.created_at,
        updated_at=order.updated_at,
        production_count=len(productions),
        total_quantity=sum(int(row.planned_quantity or 0) for row in productions),
        cutting_status=(
            BrandedCuttingProgress.COMPLETED
            if cutting_states and all(state == BrandedCuttingProgress.COMPLETED for state in cutting_states)
            else BrandedCuttingProgress.PARTIAL
            if any(state != BrandedCuttingProgress.NOT_STARTED for state in cutting_states)
            else BrandedCuttingProgress.NOT_STARTED
        ),
        productions=[
            BrandedProductionOut(
                id=row.id,
                order_no=row.order_no,
                production_no=row.production_no,
                model_id=row.model_id,
                model=(
                    BrandedModelOut(**model_by_id[int(row.model_id)])
                    if int(row.model_id) in model_by_id
                    else None
                ),
                planned_quantity=row.planned_quantity,
                status=row.status,
                cutting_status=cutting_by_id.get(row.id, BrandedCuttingProgress.NOT_STARTED),
                cutting_quantity=cutting_details_by_id.get(row.id, {}).get("cutting_quantity", 0),
                cutting_departments=[
                    BrandedCuttingDepartmentOut(**department)
                    for department in cutting_details_by_id.get(row.id, {}).get("cutting_departments", [])
                ],
            )
            for row in productions
        ],
    )



def list_branded_orders(
    db: Session, status: BrandedPlanningOrderStatus | None
) -> list[BrandedPlanningOrderOut]:
    """Return the branded planning orders with their model and cutting state."""
    query = db.query(BrandedPlanningOrder).options(joinedload(BrandedPlanningOrder.production_orders))
    if status:
        query = query.filter(BrandedPlanningOrder.status == status.value)
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
    model_by_id = {int(model.id): branded_model_payload(model) for model in models}
    production_ids = [production.id for order in rows for production in order.production_orders]
    cutting_by_production: dict[int, list] = {}
    if production_ids:
        cutting_rows = db.query(
            WorkOrder.production_order_id, WorkOrder.status, WorkOrder.actual_output_qty,
            Department.code, Department.name,
        ).join(Department, Department.id == WorkOrder.department_id).filter(
            WorkOrder.production_order_id.in_(production_ids),
            WorkOrder.operation == "cutting",
            WorkOrder.status.notin_(("cancelled", "rejected")),
        ).all()
        for work in cutting_rows:
            cutting_by_production.setdefault(work.production_order_id, []).append(work)
    cutting_by_id: dict[int, BrandedCuttingProgress] = {
        production_id: (
            BrandedCuttingProgress.COMPLETED
            if all(work.status == "completed" for work in works)
            else BrandedCuttingProgress.PARTIAL
            if any(work.status == "completed" or work.actual_output_qty > 0 for work in works)
            else BrandedCuttingProgress.NOT_STARTED
        )
        for production_id, works in cutting_by_production.items()
    }
    cutting_details_by_id = {
        production_id: {
            "cutting_quantity": sum(int(work.actual_output_qty or 0) for work in works),
            "cutting_departments": [
                {"code": code, "name": name}
                for code, name in sorted({(work.code, work.name) for work in works})
            ],
        }
        for production_id, works in cutting_by_production.items()
    }
    return [branded_order_payload(row, model_by_id, cutting_by_id, cutting_details_by_id) for row in rows]


def branded_order_parties(db: Session) -> dict:
    """Return the selectable parties for a branded order."""
    customers = db.query(Customer).order_by(Customer.name.asc()).all()
    return {
        "companies": [{"type": key.value, "name": name} for key, name in BRANDED_ORDER_PARTIES.items()],
        "customers": [{"id": row.id, "name": row.name} for row in customers],
    }


def branded_order_customers(db: Session, q: str) -> list[dict]:
    """Return the customers that can be named on a branded order."""
    query = db.query(Customer.id, Customer.name)
    if q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(Customer.name.ilike(pattern, escape="\\"))
    return [{"id": row.id, "name": row.name} for row in query.order_by(Customer.name, Customer.id).limit(50)]


def create_branded_order(
    db: Session, payload: BrandedPlanningOrderIn, current: User
) -> BrandedPlanningOrderOut:
    """Open one branded planning order for a company party or a customer."""
    ordered_for_type = payload.ordered_for_type
    customer_id = payload.customer_id
    if ordered_for_type is BrandedPlanningOrderType.CUSTOMER:
        customer = db.get(Customer, customer_id) if customer_id else None
        if not customer:
            raise HTTPException(404, "Customer not found")
        ordered_for_name = customer.name
    elif ordered_for_type in BRANDED_ORDER_PARTIES:
        customer_id = None
        ordered_for_name = BRANDED_ORDER_PARTIES[ordered_for_type]
    else:
        raise HTTPException(400, "Choose Milana, Eco Cotton, Besttex, or a customer")

    order = insert_branded_planning_order(
        db,
        BrandedPlanningOrderInsert(
            order_no=next_branded_planning_order_no(db),
            ordered_for_type=ordered_for_type,
            customer_id=customer_id,
            ordered_for_name=ordered_for_name,
            status=BrandedPlanningOrderStatus.OPEN,
            notes=str(payload.notes or "").strip() or None,
            created_by=current.id,
        ),
    )
    log_action(
        db, current, "create", "BrandedPlanningOrder", order.id,
        new_value={"order_no": order.order_no, "ordered_for": order.ordered_for_name},
    )
    db.commit()
    db.refresh(order)
    return branded_order_payload(order)


def export_branded_order_workbook(db: Session, order_id: int) -> bytes:
    """Return the workbook bytes of one branded planning order."""
    order = db.get(BrandedPlanningOrder, order_id)
    if not order:
        raise HTTPException(404, "Branded order not found")
    return build_branded_order_workbook(db, order)
