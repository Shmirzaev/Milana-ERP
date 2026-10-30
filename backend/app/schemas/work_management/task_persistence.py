"""Schema-owned Task inserts and mapped user-update/completion participation."""
from datetime import datetime
from sqlalchemy.orm import Session, object_session

from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.libs.types.work_management import TaskCompletionTimestampChange, TaskUpdateCommand
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


def apply_user_task_update(
    db: Session,
    row: Task,
    command: TaskUpdateCommand,
    *,
    completed_at: TaskCompletionTimestampChange,
) -> None:
    """Apply known user PATCH fields to an attached Task without flushing."""
    if object_session(row) is not db:
        raise ValueError("Task PATCH requires the caller's attached Task row")
    fields = command.present_fields
    if "title" in fields:
        row.title = command.title
    if "description" in fields:
        row.description = command.description
    if "assigned_to" in fields:
        row.assigned_to = command.assigned_to
    if "status" in fields:
        row.status = command.status.value if command.status is not None else None
    if "priority" in fields:
        row.priority = command.priority.value if command.priority is not None else None
    if "due_date" in fields:
        row.due_date = command.due_date
    if "entity_type" in fields:
        row.entity_type = command.entity_type
    if "entity_id" in fields:
        row.entity_id = command.entity_id
    if completed_at.should_write:
        row.completed_at = completed_at.value


def apply_user_task_completion(
    db: Session,
    row: Task,
    *,
    completed_at: datetime,
) -> None:
    """Stage the existing user-facing completion fields on the caller's Session."""
    if object_session(row) is not db:
        raise ValueError("Task completion requires the caller's attached Task row")
    row.status = TaskStatus.COMPLETED.value
    row.completed_at = completed_at


def delete_user_task_row(db: Session, row: Task) -> None:
    """Stage a user-facing Task delete in its owning transaction."""
    if object_session(row) is not db:
        raise ValueError("Task deletion requires the caller's attached Task row")
    db.delete(row)
