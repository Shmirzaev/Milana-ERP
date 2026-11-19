from fastapi import APIRouter

from app.core.deps import DbSession, CurrentUser
from app.libs.dto.work_management.tasks import TaskAssigneeOption, TaskIn, TaskUpdate, TaskOut
from app.models.audit_service import log_action
from app.models.work_management.tasks_service import (
    delete_task as delete_task_operation,
    complete_task as complete_task_operation,
    create_task as create_task_operation,
    get_task as get_task_operation,
    list_tasks as list_tasks_operation,
    open_task_count as open_task_count_operation,
    list_task_assignees as list_task_assignees_operation,
    update_task as update_task_operation,
)
from app.libs.enums.work_management import TaskStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/assignees", response_model=list[TaskAssigneeOption])
def list_task_assignees(db: DbSession, current: CurrentUser):
    return list_task_assignees_operation(db, current)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: DbSession, current: CurrentUser,
    scope: str = "mine",  # mine | created | all (manager/admin only)
    status: TaskStatus | None = None,
):
    return list_tasks_operation(db, current, scope, status)


@router.get("/open-count")
def open_task_count(db: DbSession, current: CurrentUser):
    return open_task_count_operation(db, current)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(payload: TaskIn, db: DbSession, current: CurrentUser):
    return create_task_operation(payload, db, current, audit=log_action)


@router.get("/{tid}", response_model=TaskOut)
def get_task(tid: int, db: DbSession, current: CurrentUser):
    return get_task_operation(db, current, tid)


@router.patch("/{tid}", response_model=TaskOut)
def update_task(tid: int, payload: TaskUpdate, db: DbSession, current: CurrentUser):
    return update_task_operation(tid, payload, db, current, audit=log_action)


@router.delete("/{tid}", status_code=204)
def delete_task(tid: int, db: DbSession, current: CurrentUser):
    return delete_task_operation(tid, db, current, audit=log_action)


@router.post("/{tid}/complete", response_model=TaskOut)
def complete_task(tid: int, db: DbSession, current: CurrentUser):
    return complete_task_operation(tid, db, current, audit=log_action)
