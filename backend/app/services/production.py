"""Production service: build production orders and work orders, manage flow."""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    ProductionOrder, ProductionOrderItem, WorkOrder, Department, Model, SalesOrder,
)
from app.services.numbering import next_production_order_no


# Department code -> operation
DEPT_OPS = [
    ("CUT", "cutting"),
    ("PRT", "printing"),
    ("SEW", "sewing"),
    ("PKG", "packaging"),
    ("FGS", "storage_transfer"),
]


def _get_dept(db: Session, code: str) -> Department:
    dept = db.query(Department).filter(Department.code == code).first()
    if not dept:
        raise HTTPException(400, f"Department '{code}' not configured")
    return dept


def create_production_order(
    db: Session,
    *,
    production_type: str,
    model_id: int,
    sales_order_id: int | None = None,
    collection_id: int | None = None,
    planned_quantity: int = 0,
    start_date: datetime | None = None,
    deadline: datetime | None = None,
    destination_warehouse_id: int | None = None,
    items: list[dict] | None = None,
    created_by: int | None = None,
) -> ProductionOrder:
    if production_type not in ("client_order", "branded_stock"):
        raise HTTPException(400, "Invalid production_type")

    model = db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if production_type == "branded_stock" and model.status != "approved":
        raise HTTPException(400, "Branded stock production requires an approved model")
    if production_type == "client_order" and not sales_order_id:
        raise HTTPException(400, "Client order production requires sales_order_id")

    if sales_order_id:
        so = db.get(SalesOrder, sales_order_id)
        if not so:
            raise HTTPException(404, "Sales order not found")

    po = ProductionOrder(
        production_no=next_production_order_no(db),
        production_type=production_type,
        sales_order_id=sales_order_id,
        collection_id=collection_id,
        model_id=model_id,
        status="new",
        planned_quantity=planned_quantity or sum(int(i.get("planned_quantity", 0)) for i in (items or [])),
        start_date=start_date,
        deadline=deadline,
        destination_warehouse_id=destination_warehouse_id,
        created_by=created_by,
    )
    db.add(po)
    db.flush()

    for it in (items or []):
        db.add(ProductionOrderItem(
            production_order_id=po.id,
            model_id=it.get("model_id", model_id),
            color=it["color"],
            size=it["size"],
            planned_quantity=int(it.get("planned_quantity", 0)),
        ))
    db.flush()
    return po


def create_work_orders(db: Session, production_order_id: int, include_printing: bool = False) -> list[WorkOrder]:
    po = db.get(ProductionOrder, production_order_id)
    if not po:
        raise HTTPException(404, "Production order not found")

    existing_ops = {wo.operation for wo in db.query(WorkOrder).filter(WorkOrder.production_order_id == po.id).all()}
    created: list[WorkOrder] = []

    for code, op in DEPT_OPS:
        if op == "printing" and not include_printing:
            continue
        if op in existing_ops:
            continue
        dept = _get_dept(db, code)
        wo = WorkOrder(
            production_order_id=po.id,
            department_id=dept.id,
            operation=op,
            status="waiting",
            planned_input_qty=po.planned_quantity,
            planned_output_qty=po.planned_quantity,
        )
        db.add(wo)
        created.append(wo)

    po.status = "planning"
    db.flush()
    return created
