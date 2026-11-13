"""Read Sewing-ledger availability without manufacturing acceptance receipts."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.libs.enums.packaging import PackagingDepartment
from app.libs.enums.production import WorkOrderStatus
from app.schemas import Department, PackagingRecord, SewingRecord, WorkOrder


@dataclass(frozen=True)
class PackagingAvailableOrder:
    work_order_id: int
    production_order_id: int
    received_quantity: int
    last_received_at: datetime | None


def available_orders(db: Session, department: PackagingDepartment) -> list[PackagingAvailableOrder]:
    """Legacy received_quantity means proven passed output; no write occurs here.

    Dedicated batch work orders take precedence across departments. An order-wide
    work order must never borrow output routed to a different factory/Nastil.
    """
    targets = db.query(WorkOrder).join(Department, Department.id == WorkOrder.department_id).filter(
        WorkOrder.operation == "packaging", WorkOrder.status != WorkOrderStatus.CANCELLED,
        Department.code == department,
    ).all()
    order_ids = {row.production_order_id for row in targets}
    if not order_ids:
        return []
    all_targets = db.query(WorkOrder).filter(
        WorkOrder.production_order_id.in_(order_ids), WorkOrder.operation == "packaging",
        WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).order_by(WorkOrder.id.desc()).all()
    exact = {}
    shared = {}
    for row in all_targets:
        if row.production_batch_id is None:
            shared.setdefault(row.production_order_id, row.id)
        else:
            exact.setdefault((row.production_order_id, row.production_batch_id), row.id)
    sewing_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    sewing = db.query(
        WorkOrder.production_order_id, sewing_batch,
        func.sum(SewingRecord.passed_qty), func.max(SewingRecord.created_at),
    ).join(WorkOrder, WorkOrder.id == SewingRecord.work_order_id).filter(
        WorkOrder.production_order_id.in_(order_ids), WorkOrder.operation == "sewing",
        WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).group_by(WorkOrder.production_order_id, sewing_batch).all()
    totals: dict[int, tuple[int, datetime | None]] = {}
    allowed = {row.id for row in targets}
    for order_id, batch_id, quantity, timestamp in sewing:
        target_id = exact.get((order_id, batch_id), shared.get(order_id))
        if target_id not in allowed:
            continue
        previous, last = totals.get(target_id, (0, None))
        totals[target_id] = (previous + max(0, int(quantity or 0)), max(last, timestamp) if last and timestamp else last or timestamp)
    return [PackagingAvailableOrder(row.id, row.production_order_id, *totals[row.id])
            for row in targets if row.id in totals and totals[row.id][0] > 0]


def input_budgets(db: Session, work_order: WorkOrder) -> dict[int | None, dict[str, int]]:
    """Only actual passed Sewing less saved Packaging input is consumable.

    Historical manual/scan receipts are retained as audit history, not a second
    acceptance gate and never evidence of additional produced garments.
    """
    sewing_batch = func.coalesce(SewingRecord.production_batch_id, WorkOrder.production_batch_id)
    sewn = dict(db.query(sewing_batch, func.sum(SewingRecord.passed_qty)).join(
        WorkOrder, WorkOrder.id == SewingRecord.work_order_id,
    ).filter(
        WorkOrder.production_order_id == work_order.production_order_id,
        WorkOrder.operation == "sewing", WorkOrder.status != WorkOrderStatus.CANCELLED,
    ).group_by(sewing_batch).all())
    packaging_batch = func.coalesce(PackagingRecord.production_batch_id, WorkOrder.production_batch_id)
    inputs = dict(db.query(packaging_batch, func.sum(PackagingRecord.input_qty)).join(
        WorkOrder, WorkOrder.id == PackagingRecord.work_order_id,
    ).filter(WorkOrder.id == work_order.id).group_by(packaging_batch).all())
    return {batch_id: {
        "sewing_output_qty": max(0, int(sewn.get(batch_id) or 0)),
        "input_limit_qty": max(0, int(sewn.get(batch_id) or 0)),
        "available_input_qty": max(0, int(sewn.get(batch_id) or 0) - int(inputs.get(batch_id) or 0)),
    } for batch_id in sewn.keys() | inputs.keys()}
