"""Same-Session writes participating in the shared Sewing output operation."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.libs.enums.production import WorkOrderStatus
from app.libs.types.production import SewingOutputAccounting, SewingOutputRecordValues

from app.schemas.production.production import ProductionOrder, SewingRecord, WorkOrder
from app.schemas.production.sewing_assignment import SewingAssignment


def insert_sewing_output(db: Session, values: SewingOutputRecordValues) -> SewingRecord:
    row = SewingRecord(
        work_order_id=values.work_order_id,
        production_batch_id=values.production_batch_id,
        sewing_assignment_id=values.sewing_assignment_id,
        input_qty=values.input_qty,
        sewn_qty=values.sewn_qty,
        passed_qty=values.passed_qty,
        failed_qty=values.failed_qty,
        rework_qty=values.rework_qty,
        rejected_qty=values.rejected_qty,
        size_quantities=values.size_quantities,
        defect_reason=values.defect_reason,
        line_name=values.line_name,
        operator_id=values.operator_id,
        notes=values.notes,
    )
    db.add(row)
    db.flush()
    return row


def apply_sewing_output_accounting(
    *, row: SewingRecord, work_order: WorkOrder, assignment: SewingAssignment | None,
    accounting: SewingOutputAccounting,
) -> None:
    """Apply calculated production values; all policy/calculation stays in the service."""
    row.assignment_applied_qty = accounting.assignment_applied_qty
    work_order.actual_input_qty = accounting.actual_input_qty
    work_order.actual_output_qty = accounting.actual_output_qty
    work_order.passed_qty = accounting.passed_qty
    work_order.failed_qty = accounting.failed_qty
    work_order.rework_qty = accounting.rework_qty
    if assignment is not None:
        if accounting.assignment_quantity is not None:
            assignment.quantity = accounting.assignment_quantity
        if accounting.assignment_completed_qty is not None:
            assignment.completed_qty = accounting.assignment_completed_qty
        if accounting.assignment_status is not None:
            assignment.status = accounting.assignment_status.value
        if accounting.assignment_actual_start is not None:
            assignment.actual_start = accounting.assignment_actual_start
        if accounting.assignment_actual_end is not None:
            assignment.actual_end = accounting.assignment_actual_end


def set_work_order_accessory_block(work_order: WorkOrder, *, blocked: bool, reason: str | None) -> None:
    work_order.is_blocked = blocked
    work_order.block_reason = reason


def set_work_order_department(work_order: WorkOrder, department_id: int) -> None:
    work_order.department_id = department_id


def set_work_order_actual_input(work_order: WorkOrder, quantity: int) -> None:
    work_order.actual_input_qty = quantity


def raise_sewing_output_plans(
    sewing: WorkOrder, downstream: list[WorkOrder], passed_qty: int,
) -> None:
    sewing.planned_output_qty = passed_qty
    for work_order in downstream:
        work_order.planned_input_qty = max(int(work_order.planned_input_qty or 0), passed_qty)
        work_order.planned_output_qty = max(int(work_order.planned_output_qty or 0), passed_qty)


def set_work_order_transition(
    work_order: WorkOrder, *, status: WorkOrderStatus | None = None,
    start_time: datetime | None = None, end_time: datetime | None = None,
    clear_start: bool = False, clear_end: bool = False,
) -> None:
    if status is not None:
        work_order.status = status.value
    if clear_start:
        work_order.start_time = None
    elif start_time is not None:
        work_order.start_time = start_time
    if clear_end:
        work_order.end_time = None
    elif end_time is not None:
        work_order.end_time = end_time


def set_production_order_status(order: ProductionOrder, status: str) -> None:
    order.status = status
