from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, is_admin, user_permissions
from app.models import Task, User
from app.schemas.tasks import TaskIn, TaskUpdate, TaskOut
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _can_manage(user: User) -> bool:
    """Admins and Management can create / reassign / delete tasks for anyone."""
    if is_admin(user):
        return True
    if user.role and user.role.name in ("Admin", "Management"):
        return True
    perms = user_permissions(user)
    return "tasks.manage" in perms or "management.approve" in perms


def _task_link(t: Task) -> str | None:
    """Build a frontend URL for a task notification when the task references
    a concrete entity. Returns None when no mapping exists."""
    et = (t.entity_type or "").lower()
    eid = t.entity_id
    if not eid:
        return None
    mapping = {
        "salesorder": f"/sales-orders/{eid}",
        "sales_order": f"/sales-orders/{eid}",
        "productionorder": f"/production-orders/{eid}",
        "production_order": f"/production-orders/{eid}",
        "workorder": f"/work-orders/{eid}",
        "work_order": f"/work-orders/{eid}",
        "bundle": f"/bundles/{eid}",
        "package": f"/packages/{eid}",
        "shipment": "/shipments",
        "invoice": "/finance",
    }
    return mapping.get(et)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    db: DbSession, current: CurrentUser,
    scope: str = "mine",  # mine | created | all (manager/admin only)
    status: str | None = None,
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
        qry = qry.filter(Task.status == status)
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
    is_manager = _can_manage(current)
    requested_assignee = payload.assigned_to

    # Special manager-only broadcast mode: assigned_to == -1 means "everyone".
    if requested_assignee == -1:
        if not is_manager:
            raise HTTPException(403, "Only managers can assign tasks to everyone")
        targets = db.query(User).filter(User.is_active.is_(True)).order_by(User.id).all()
        if not targets:
            raise HTTPException(404, "No active users found")

        created: list[Task] = []
        for user in targets:
            t = Task(
                title=payload.title,
                description=payload.description,
                assigned_to=user.id,
                created_by=current.id,
                status=payload.status,
                priority=payload.priority,
                due_date=payload.due_date,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
            )
            db.add(t)
            db.flush()
            created.append(t)
            notify(
                db, user_id=user.id,
                title=f"New task: {t.title}",
                message=(t.description or "")[:280],
                link=_task_link(t),
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

    # Non-managers can only assign tasks to themselves.
    assigned = requested_assignee or current.id
    if assigned != current.id and not is_manager:
        raise HTTPException(403, "Only managers can assign tasks to other users")
    if not db.get(User, assigned):
        raise HTTPException(404, "Assigned user not found")

    t = Task(
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
    db.add(t)
    db.flush()

    # Notify the assignee unless they assigned to themselves.
    if assigned != current.id:
        notify(
            db, user_id=assigned,
            title=f"New task: {t.title}",
            message=(t.description or "")[:280],
            link=_task_link(t),
        )

    log_action(db, current, "create", "Task", t.id, new_value={"title": t.title, "assigned_to": assigned})
    db.commit()
    db.refresh(t)
    return t


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
    is_manager = _can_manage(current) or t.created_by == current.id

    if not is_manager:
        if not is_assignee:
            raise HTTPException(403, "Not allowed")
        # Restrict assignees to status-only changes.
        allowed = {"status"}
        if set(changes.keys()) - allowed:
            raise HTTPException(403, "Assignees can only change status")

    previous_assignee = t.assigned_to
    for k, v in changes.items():
        setattr(t, k, v)

    if changes.get("status") == "completed" and not t.completed_at:
        t.completed_at = datetime.now(timezone.utc)
    elif changes.get("status") and changes["status"] != "completed":
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
    t.status = "completed"
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
