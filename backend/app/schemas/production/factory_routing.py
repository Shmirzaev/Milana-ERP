"""Persistence for an already validated, locked Nastil routing operation."""
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from app.schemas import Bundle, SewingAssignment, WorkOrder


def insert_batch_work_order(db: Session, source: WorkOrder, batch_id: int, department_id: int,
                            quantity: int, received: int) -> WorkOrder:
    row = WorkOrder(production_order_id=source.production_order_id, production_batch_id=batch_id,
                    operation=source.operation, department_id=department_id,
                    planned_input_qty=quantity, planned_output_qty=quantity,
                    actual_input_qty=received, status="in_progress" if received else "waiting",
                    deadline=source.deadline)
    db.add(row)
    db.flush()
    return row


def assign_batch_work_order(row: WorkOrder, department_id: int) -> None:
    row.department_id = department_id
    row.sewing_flow_id = None


def reduce_shared_plan(row: WorkOrder, quantity: int) -> None:
    floor = max(row.actual_output_qty, row.passed_qty + row.failed_qty)
    row.planned_input_qty = max(floor, row.planned_input_qty - quantity)
    row.planned_output_qty = max(floor, row.planned_output_qty - quantity)


def assign_bundle_factory(bundle: Bundle, factory: str, sewing_id: int, packaging_id: int,
                          sewing_ids: set[int], packaging_ids: set[int]) -> None:
    bundle.sewing_factory_code = factory
    if bundle.current_department_id in sewing_ids:
        bundle.current_department_id = sewing_id
    if bundle.next_department_id in sewing_ids:
        bundle.next_department_id = sewing_id
    elif bundle.next_department_id in packaging_ids:
        bundle.next_department_id = packaging_id


def cancel_unused_assignment(row: SewingAssignment) -> None:
    row.status = "cancelled"


def complete_empty_shared_stage(row: WorkOrder) -> None:
    row.planned_input_qty = row.planned_output_qty = 0
    row.status = "completed"
    row.end_time = datetime.now(timezone.utc)
