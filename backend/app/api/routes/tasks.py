from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser
from app.schemas import Task
from app.libs.dto.work_management.tasks import TaskIn, TaskUpdate, TaskOut
from app.models.audit_service import log_action
from app.models.work_management.tasks_service import (
    complete_task as complete_task_operation,
    _can_manage, create_task as create_task_operation,
    update_task as update_task_operation,
)
from app.libs.enums.work_management import TaskStatus

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
            Task.status.in_(("pending", "in_progress")),
        )
        .scalar()
        or 0
    )
    return {"count": int(count)}


@router.post("", response_model=TaskOut, status_code=201)
def create_task(payload: TaskIn, db: DbSession, current: CurrentUser):
    return create_task_operation(payload, db, current, audit=log_action)


@router.get("/{tid}", response_model=TaskOut)
def get_task(tid: int, db: DbSession, current: CurrentUser):
    t = db.get(Task, tid)
    if not t: raise HTTPException(404, "Task not found")
    if t.assigned_to != current.id and t.created_by != current.id and not _can_manage(current):
        raise HTTPException(403, "Not allowed")
    return t


@router.patch("/{tid}", response_model=TaskOut)
def update_task(tid: int, payload: TaskUpdate, db: DbSession, current: CurrentUser):
    return update_task_operation(tid, payload, db, current, audit=log_action)


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
    return complete_task_operation(tid, db, current, audit=log_action)
