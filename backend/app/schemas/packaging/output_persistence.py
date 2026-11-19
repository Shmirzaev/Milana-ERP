"""Packaging evidence writes participate in the caller's outer transaction."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.libs.dto.production.production import PackagingRecordIn
from app.libs.enums.production import WorkOrderStatus
from app.schemas import PackagingRecord, WorkOrder


def insert_output(db: Session, work: WorkOrder, payload: PackagingRecordIn, *,
                  operator_id: int, actual_input_qty: int, actual_output_qty: int,
                  passed_qty: int, failed_qty: int, started_at: datetime | None = None) -> PackagingRecord:
    row = PackagingRecord(**{**payload.model_dump(), "operator_id": operator_id})
    db.add(row)
    db.flush()
    work.actual_input_qty = actual_input_qty
    work.actual_output_qty = actual_output_qty
    work.passed_qty = passed_qty
    work.failed_qty = failed_qty
    if started_at is not None:
        work.status = WorkOrderStatus.IN_PROGRESS
        if work.start_time is None:
            work.start_time = started_at
    return row
