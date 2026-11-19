"""Assignment persistence for sewing batch receipt; caller owns transaction."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.schemas.production.production import WorkOrder
from app.schemas.production.sewing_assignment import SewingAssignment


def create_receipt_assignment(
    db: Session, *, work_order: WorkOrder, production_batch_id: int,
    sewing_flow_id: int, quantity: int, now: datetime,
    planned_end: datetime | None, actor_id: int, notes: str,
) -> SewingAssignment:
    assignment = SewingAssignment(
        work_order_id=work_order.id, production_batch_id=production_batch_id,
        sewing_flow_id=sewing_flow_id, quantity=quantity, planned_start=now,
        planned_end=planned_end, actual_start=now, status="in_progress",
        notes=notes, created_by=actor_id,
    )
    db.add(assignment)
    db.flush()
    return assignment


def resize_receipt_assignment(assignment: SewingAssignment, quantity: int) -> None:
    assignment.quantity = quantity


def start_receipt_assignment(
    assignment: SewingAssignment, work_order: WorkOrder, sewing_flow_id: int, now: datetime,
) -> None:
    if assignment.status == "planned":
        assignment.status = "in_progress"
    if assignment.actual_start is None:
        assignment.actual_start = now
    if not work_order.sewing_flow_id:
        work_order.sewing_flow_id = sewing_flow_id
