"""Work-management operations for user Tasks and system participants."""
from datetime import datetime, timezone
from typing import Literal, cast

from sqlalchemy.orm import Session

from app.core.deps import is_admin, user_permissions
from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.libs.dto.work_management.tasks import TaskIn, TaskUpdate
from app.libs.types.work_management import (
    TaskCompletionTimestampChange,
    TaskUpdateCommand,
    TaskUpdateField,
)
from app.models.audit_service import log_action
from app.models.notifications_service import max_bulk_recipients, notify, notify_many
from app.models.user_access_service import access_configured, permission_denied
from app.schemas import Task, User
from app.schemas.work_management.task_persistence import (
    add_stock_shortage_task,
    add_user_created_task,
    apply_user_task_update,
)


TaskCreateRefusalReason = Literal[
    "manager_required",
    "assignee_missing",
    "recipient_limit_exceeded",
    "no_active_recipients",
]


class TaskCreateRefused(Exception):
    """A business-rule refusal translated to HTTP by the route."""

    def __init__(self, reason: TaskCreateRefusalReason, *, recipient_limit: int | None = None):
        self.reason = reason
        self.recipient_limit = recipient_limit
        super().__init__(reason)


def can_manage_tasks(user: User) -> bool:
    """Keep the existing effective task-manager permission policy."""
    if permission_denied(user, "tasks.manage"):
        return False
    if is_admin(user):
        return True
    if not access_configured(user) and user.role and user.role.name in ("Admin", "Management"):
        return True
    permissions = user_permissions(user)
    return "tasks.manage" in permissions or "management.approve" in permissions


def task_notification_link(task: Task) -> str | None:
    """Build the existing task-notification link for a concrete entity."""
    entity_type = (task.entity_type or "").lower()
    entity_id = task.entity_id
    if not entity_id:
        return None
    return {
        "salesorder": f"/sales-orders/{entity_id}",
        "sales_order": f"/sales-orders/{entity_id}",
        "productionorder": f"/production-orders/{entity_id}",
        "production_order": f"/production-orders/{entity_id}",
        "workorder": f"/work-orders/{entity_id}",
        "work_order": f"/work-orders/{entity_id}",
        "bundle": f"/bundles/{entity_id}",
        "package": f"/packages/{entity_id}",
        "shipment": "/shipments",
        "invoice": "/finance",
    }.get(entity_type)


def create_user_task(db: Session, current: User, payload: TaskIn) -> Task:
    """Create a self/assigned/broadcast task with its existing side effects.

    This service owns the single outer commit. Schema and shared notification
    operations stage writes on this Session; the audit service retains its
    deferred PostgreSQL hash-chain behavior.
    """
    manager = can_manage_tasks(current)
    requested_assignee = payload.assigned_to

    if requested_assignee == -1:
        if not manager:
            raise TaskCreateRefused("manager_required")
        recipient_limit = max_bulk_recipients()
        target_ids = [
            row.id
            for row in (
                db.query(User.id)
                .filter(User.is_active.is_(True))
                .order_by(User.id)
                .limit(recipient_limit + 1)
                .all()
            )
        ]
        if len(target_ids) > recipient_limit:
            raise TaskCreateRefused("recipient_limit_exceeded", recipient_limit=recipient_limit)
        if not target_ids:
            raise TaskCreateRefused("no_active_recipients")

        created = [
            add_user_created_task(
                db,
                title=payload.title,
                description=payload.description,
                assigned_to=user_id,
                created_by=current.id,
                status=payload.status,
                priority=payload.priority,
                due_date=payload.due_date,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
            )
            for user_id in target_ids
        ]
        notify_many(
            db,
            user_ids=target_ids,
            title=f"New task: {payload.title}",
            message=(payload.description or "")[:280],
            link=task_notification_link(created[0]),
        )
        first_task = created[0]
        log_action(
            db,
            current,
            "create",
            "Task",
            first_task.id,
            new_value={
                "title": payload.title,
                "assigned_to": "everyone",
                "created_count": len(created),
            },
        )
        db.commit()
        db.refresh(first_task)
        return first_task

    assigned = requested_assignee or current.id
    if assigned != current.id and not manager:
        raise TaskCreateRefused("manager_required")
    assignee = db.get(User, assigned)
    if assignee is None:
        raise TaskCreateRefused("assignee_missing")

    task = add_user_created_task(
        db,
        title=payload.title,
        description=payload.description,
        assigned_to=assigned,
        created_by=current.id,
        status=payload.status,
        priority=payload.priority,
        due_date=payload.due_date,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )
    db.flush()
    if assigned != current.id:
        notify(
            db,
            user_id=assigned,
            title=f"New task: {task.title}",
            message=(task.description or "")[:280],
            link=task_notification_link(task),
        )
    log_action(db, current, "create", "Task", task.id,
               new_value={"title": task.title, "assigned_to": assigned})
    db.commit()
    db.refresh(task)
    return task


TaskUpdateRefusalReason = Literal[
    "task_missing",
    "not_allowed",
    "assignee_status_only",
    "manager_required",
    "assignee_missing",
]


class TaskUpdateRefused(Exception):
    """A Task PATCH refusal translated to the established HTTP response."""

    def __init__(self, reason: TaskUpdateRefusalReason):
        self.reason = reason
        super().__init__(reason)


def _task_update_command(payload: TaskUpdate) -> TaskUpdateCommand:
    """Keep the DTO's declared fields and explicit-null presence as a typed input."""
    present_fields = cast(frozenset[TaskUpdateField], frozenset(payload.model_fields_set))
    return TaskUpdateCommand(
        present_fields=present_fields,
        title=payload.title,
        description=payload.description,
        assigned_to=payload.assigned_to,
        status=payload.status,
        priority=payload.priority,
        due_date=payload.due_date,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
    )


def _task_update_audit_values(command: TaskUpdateCommand) -> dict[str, object]:
    """Serialize only supplied PATCH fields, retaining null and enum wire values."""
    values: dict[str, object] = {}
    fields = command.present_fields
    if "title" in fields:
        values["title"] = command.title
    if "description" in fields:
        values["description"] = command.description
    if "assigned_to" in fields:
        values["assigned_to"] = command.assigned_to
    if "status" in fields:
        values["status"] = command.status.value if command.status is not None else None
    if "priority" in fields:
        values["priority"] = command.priority.value if command.priority is not None else None
    if "due_date" in fields:
        values["due_date"] = command.due_date
    if "entity_type" in fields:
        values["entity_type"] = command.entity_type
    if "entity_id" in fields:
        values["entity_id"] = command.entity_id
    return values


def update_user_task(db: Session, current: User, task_id: int, payload: TaskUpdate) -> Task:
    """Update one Task, preserving its authorization, side-effect and commit policy."""
    task = db.get(Task, task_id)
    if task is None:
        raise TaskUpdateRefused("task_missing")

    command = _task_update_command(payload)
    is_assignee = task.assigned_to == current.id
    is_manager = can_manage_tasks(current)
    can_edit = is_manager or task.created_by == current.id
    if not can_edit:
        if not is_assignee:
            raise TaskUpdateRefused("not_allowed")
        if command.present_fields - {"status"}:
            raise TaskUpdateRefused("assignee_status_only")

    previous_assignee = task.assigned_to
    if "assigned_to" in command.present_fields and command.assigned_to != previous_assignee:
        if command.assigned_to != current.id and not is_manager:
            raise TaskUpdateRefused("manager_required")
        if command.assigned_to is not None and db.get(User, command.assigned_to) is None:
            raise TaskUpdateRefused("assignee_missing")

    timestamp_change = TaskCompletionTimestampChange(should_write=False)
    if "status" in command.present_fields:
        if command.status is TaskStatus.COMPLETED and not task.completed_at:
            timestamp_change = TaskCompletionTimestampChange(
                should_write=True,
                value=datetime.now(timezone.utc),
            )
        elif command.status is not None and command.status is not TaskStatus.COMPLETED:
            timestamp_change = TaskCompletionTimestampChange(should_write=True, value=None)

    apply_user_task_update(db, task, command, completed_at=timestamp_change)

    if (
        "assigned_to" in command.present_fields
        and task.assigned_to
        and task.assigned_to != previous_assignee
    ):
        notify(
            db,
            user_id=task.assigned_to,
            title=f"Task reassigned to you: {task.title}",
            message=(task.description or "")[:280],
            link=task_notification_link(task),
        )

    log_action(
        db,
        current,
        "update",
        "Task",
        task.id,
        new_value=_task_update_audit_values(command),
    )
    db.commit()
    db.refresh(task)
    return task


def create_stock_shortage_task(
    db: Session, *, title: str, description: str, assigned_to: int,
    created_by: int, due_date: datetime | None,
) -> None:
    add_stock_shortage_task(db, title=title, description=description,
                           assigned_to=assigned_to, created_by=created_by, due_date=due_date,
                           status=TaskStatus.PENDING, priority=TaskPriority.HIGH)
