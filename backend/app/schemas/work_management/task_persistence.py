"""Schema-owned task insert for the system stock-shortage participant only."""
from datetime import datetime
from sqlalchemy.orm import Session

from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.schemas.work_management.tasks import Task


def add_stock_shortage_task(
    db: Session, *, title: str, description: str, assigned_to: int, created_by: int,
    due_date: datetime | None, status: TaskStatus, priority: TaskPriority,
) -> None:
    """Stage the exact existing fields; no new flush, commit or deduplication."""
    db.add(Task(title=title, description=description, assigned_to=assigned_to,
                created_by=created_by, due_date=due_date,
                status=status.value, priority=priority.value))


def add_user_created_task(
    db: Session,
    *,
    title: str,
    description: str | None,
    assigned_to: int,
    created_by: int,
    status: TaskStatus,
    priority: TaskPriority,
    due_date: datetime | None,
    entity_type: str | None,
    entity_id: int | None,
) -> Task:
    """Stage one user-created task in the caller's transaction."""
    row = Task(
        title=title,
        description=description,
        assigned_to=assigned_to,
        created_by=created_by,
        status=status.value,
        priority=priority.value,
        due_date=due_date,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(row)
    return row
