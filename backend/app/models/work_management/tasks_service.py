"""Work-management participant for an already-authorized Sales stock shortage.

Sales decides when a shortage needs a task and selects the existing planning
recipient. This operation preserves its pending/high task semantics and writes
through the owning schema using that same Session. It adds no notification,
audit, authorization, flush, deduplication or transaction boundary of its own.
General user-facing task CRUD remains a separately owned migration.
"""
from datetime import datetime
from sqlalchemy.orm import Session

from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.schemas.work_management.task_persistence import add_stock_shortage_task


def create_stock_shortage_task(
    db: Session, *, title: str, description: str, assigned_to: int,
    created_by: int, due_date: datetime | None,
) -> None:
    add_stock_shortage_task(db, title=title, description=description,
                           assigned_to=assigned_to, created_by=created_by, due_date=due_date,
                           status=TaskStatus.PENDING, priority=TaskPriority.HIGH)
