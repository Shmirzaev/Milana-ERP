"""Batch routing projections for production rows already authorized by the caller."""
from sqlalchemy.orm import Session

from app.libs.dto.production.production import ProductionOrderListOut
from app.libs.enums.production import CuttingDepartmentCode, WorkOrderStatus
from app.schemas import Department, ProductionOrder, WorkOrder


def production_order_list_output(db: Session, orders: list[ProductionOrder]) -> list[ProductionOrderListOut]:
    if not orders:
        return []
    codes: dict[int, set[str]] = {}
    for order_id, code in db.query(WorkOrder.production_order_id, Department.code).join(
        Department, Department.id == WorkOrder.department_id).filter(
            WorkOrder.production_order_id.in_([order.id for order in orders]),
            WorkOrder.operation == "cutting", WorkOrder.status != WorkOrderStatus.CANCELLED).all():
        codes.setdefault(order_id, set()).add(code)
    result: list[ProductionOrderListOut] = []
    for order in orders:
        route = codes.get(order.id, set())
        code = next(iter(route)) if len(route) == 1 else None
        cutting = CuttingDepartmentCode(code) if code in (CuttingDepartmentCode.MILANA, CuttingDepartmentCode.ECO_COTTON) else None
        result.append(ProductionOrderListOut.model_validate(order).model_copy(update={"cutting_department_code": cutting}))
    return result
