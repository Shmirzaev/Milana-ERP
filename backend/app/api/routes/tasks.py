from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser
from app.schemas import Task, User
from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.libs.dto.work_management.tasks import TaskIn, TaskUpdate, TaskOut
from app.models.audit_service import log_action
from app.models.notifications_service import notify
from app.models.work_management.tasks_service import (
    TaskCreateRefused,
    can_manage_tasks as _can_manage,
    create_user_task,
    task_notification_link as _task_link,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _require_single_assignee(assigned: int | None, db: DbSession, current: User, is_manager: bool) -> None:
    if assigned != current.id and not is_manager:
        raise HTTPException(403, "Only managers can assign tasks to other users")
    if assigned is not None and not db.get(User, assigned):
        raise HTTPException(404, "Assigned user not found")


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: DbSession, current: CurrentUser,
    scope: str = "mine",  # mine | created | all (manager/admin only)
    status: TaskStatus | None = None,
):
    qry = db.query(Task)
    if scope == "all":
        if not _can_manage(current):
            raise HTTPException(403, "Only managers can list all tasks")
    elif scope == "created":
        qry = qry.filter(Task.created_by == current.id)
    else:  # mine
        qry = qry.filter(Task.assigned_to == current.id)
    if status:
        qry = qry.filter(Task.status == status.value)
    return qry.order_by(Task.id.desc()).all()


@router.get("/open-count")
def open_task_count(db: DbSession, current: CurrentUser):
    count = (
        db.query(func.count(Task.id))
        .filter(
            Task.assigned_to == current.id,
            Task.status.in_((TaskStatus.PENDING.value, TaskStatus.IN_PROGRESS.value)),
        )
        .scalar()
        or 0
    )
    return {"count": int(count)}


@router.post("", response_model=TaskOut, status_code=201)
def create_task(payload: TaskIn, db: DbSession, current: CurrentUser):
    try:
        return create_user_task(db, current, payload)
    except TaskCreateRefused as refusal:
        if refusal.reason == "manager_required":
            detail = (
                "Only managers can assign tasks to everyone"
                if payload.assigned_to == -1
                else "Only managers can assign tasks to other users"
            )
            raise HTTPException(403, detail) from refusal
        if refusal.reason == "assignee_missing":
            raise HTTPException(404, "Assigned user not found") from refusal
        if refusal.reason == "recipient_limit_exceeded":
            raise HTTPException(
                400,
                f"Recipient count exceeds ERP_MCP_MAX_BULK_RECIPIENTS={refusal.recipient_limit}",
            ) from refusal
        if refusal.reason == "no_active_recipients":
            raise HTTPException(404, "No active users found") from refusal
        raise


@router.get("/{tid}", response_model=TaskOut)
def get_task(tid: int, db: DbSession, current: CurrentUser):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404, "Task not found")
    if t.assigned_to != current.id and t.created_by != current.id and not _can_manage(current):
        raise HTTPException(403, "Not allowed")
    return t


@router.patch("/{tid}", response_model=TaskOut)
def update_task(tid: int, payload: TaskUpdate, db: DbSession, current: CurrentUser):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404, "Task not found")
    # Assignees may update status; only managers / creator may change other fields.
    changes = payload.model_dump(exclude_unset=True)
    is_assignee = t.assigned_to == current.id
    is_manager = _can_manage(current)
    can_edit = is_manager or t.created_by == current.id

    if not can_edit:
        if not is_assignee:
            raise HTTPException(403, "Not allowed")
        # Restrict assignees to status-only changes.
        allowed = {"status"}
        if set(changes.keys()) - allowed:
            raise HTTPException(403, "Assignees can only change status")

    previous_assignee = t.assigned_to
    if "assigned_to" in changes and changes["assigned_to"] != previous_assignee:
        _require_single_assignee(changes["assigned_to"], db, current, is_manager)
    for k, v in changes.items():
        stored_value = v.value if isinstance(v, (TaskStatus, TaskPriority)) else v
        setattr(t, k, stored_value)
        changes[k] = stored_value

    if changes.get("status") == TaskStatus.COMPLETED.value and not t.completed_at:
        t.completed_at = datetime.now(timezone.utc)
    elif changes.get("status") and changes["status"] != TaskStatus.COMPLETED.value:
        t.completed_at = None

    # Notify new assignee if task was reassigned.
    if "assigned_to" in changes and t.assigned_to and t.assigned_to != previous_assignee:
        notify(
            db, user_id=t.assigned_to,
            title=f"Task reassigned to you: {t.title}",
            message=(t.description or "")[:280],
            link=_task_link(t),
        )

    log_action(db, current, "update", "Task", t.id, new_value=changes)
    db.commit(); db.refresh(t)
    return t


@router.delete("/{tid}", status_code=204)
def delete_task(tid: int, db: DbSession, current: CurrentUser):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404, "Task not found")
    if not (_can_manage(current) or t.created_by == current.id):
        raise HTTPException(403, "Only managers or task creator may delete")
    db.delete(t)
    log_action(db, current, "delete", "Task", tid)
    db.commit()


@router.post("/{tid}/complete", response_model=TaskOut)
def complete_task(tid: int, db: DbSession, current: CurrentUser):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404, "Task not found")
    if t.assigned_to != current.id and not _can_manage(current):
        raise HTTPException(403, "Only the assignee or a manager may complete this task")
    t.status = TaskStatus.COMPLETED.value
    t.completed_at = datetime.now(timezone.utc)
    # Notify creator that the task is done.
    if t.created_by and t.created_by != current.id:
        notify(
            db, user_id=t.created_by,
            title=f"Task completed: {t.title}",
            message=f"Completed by user #{current.id}",
            link=_task_link(t),
        )
    log_action(db, current, "complete", "Task", t.id)
    db.commit(); db.refresh(t)
    return t
