from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from app.models import Bundle, Department, ProductionOrder, SewingFlow, WorkOrder
from app.services.factory_scope import normalize_factory_code


def production_order_factory_condition(factory_code: str):
    """Return the authoritative sewing-factory routing condition for an order.

    Bundle routing is authoritative. Department/line data is only a fallback for
    legacy orders that predate bundle-level factory routing.
    """
    factory = normalize_factory_code(factory_code)
    routed_bundle = exists().where(
        Bundle.production_order_id == ProductionOrder.id,
        Bundle.status != "cancelled",
        Bundle.sewing_factory_code == factory,
    )
    any_routed_bundle = exists().where(
        Bundle.production_order_id == ProductionOrder.id,
        Bundle.status != "cancelled",
        Bundle.sewing_factory_code.isnot(None),
    )
    legacy_department_codes = (factory, "SEW") if factory == "MIL" else (factory,)
    legacy_department = exists(
        select(WorkOrder.id)
        .join(Department, Department.id == WorkOrder.department_id)
        .where(
            WorkOrder.production_order_id == ProductionOrder.id,
            WorkOrder.operation == "sewing",
            Department.code.in_(legacy_department_codes),
        )
    )
    legacy_flow = exists(
        select(WorkOrder.id)
        .join(SewingFlow, SewingFlow.id == WorkOrder.sewing_flow_id)
        .where(
            WorkOrder.production_order_id == ProductionOrder.id,
            WorkOrder.operation == "sewing",
            SewingFlow.factory_code == factory,
        )
    )
    return or_(routed_bundle, and_(~any_routed_bundle, or_(legacy_department, legacy_flow)))


def production_order_belongs_to_factory(db, production_order_id: int, factory_code: str) -> bool:
    return bool(
        db.query(ProductionOrder.id)
        .filter(
            ProductionOrder.id == production_order_id,
            production_order_factory_condition(factory_code),
        )
        .first()
    )


def require_production_order_factory(db, production_order_id: int, factory_code: str) -> None:
    if not production_order_belongs_to_factory(db, production_order_id, factory_code):
        raise HTTPException(404, "Production order was not found in this factory")


def require_work_order_factory(db, work_order: WorkOrder, factory_code: str) -> None:
    if not production_order_belongs_to_factory(db, int(work_order.production_order_id), factory_code):
        raise HTTPException(404, "Work order was not found in this factory")

