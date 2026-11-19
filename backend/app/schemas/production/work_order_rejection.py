"""Persist the decided rejection in the coordinator's supplied transaction."""
from datetime import datetime

from app.libs.enums.production import WorkOrderStatus
from app.schemas.production.production import WorkOrder


def reject_cutting_work_order(row: WorkOrder, *, reason: str, ended_at: datetime) -> None:
    row.status = WorkOrderStatus.REJECTED.value
    row.is_blocked = True
    row.block_reason = reason
    row.end_time = ended_at
