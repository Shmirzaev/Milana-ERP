from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser
from app.schemas import Task
from app.libs.enums.work_management import TaskStatus
from app.libs.dto.work_management.tasks import TaskIn, TaskUpdate, TaskOut
from app.models.audit_service import log_action
from app.models.work_management.tasks_service import (
    TaskCreateRefused,
    TaskCompleteRefused,
    TaskUpdateRefused,
    can_manage_tasks as _can_manage,
    complete_user_task,
    create_user_task,
    update_user_task,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])


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
    try:
        return update_user_task(db, current, tid, payload)
    except TaskUpdateRefused as refusal:
        details = {
            "task_missing": (404, "Task not found"),
            "not_allowed": (403, "Not allowed"),
            "assignee_status_only": (403, "Assignees can only change status"),
            "manager_required": (403, "Only managers can assign tasks to other users"),
            "assignee_missing": (404, "Assigned user not found"),
        }
        status_code, detail = details[refusal.reason]
        raise HTTPException(status_code, detail) from refusal


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
    try:
        return complete_user_task(db, current, tid)
    except TaskCompleteRefused as refusal:
        if refusal.reason == "task_missing":
            raise HTTPException(404, "Task not found") from refusal
        raise HTTPException(
            403,
            "Only the assignee or a manager may complete this task",
        ) from refusal
