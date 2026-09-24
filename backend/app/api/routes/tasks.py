from dataclasses import dataclass
from datetime import datetime, timezone
import re
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import joinedload, load_only

from app.api.routes.notifications import _max_bulk_recipients
from app.core.deps import (
    DbSession,
    CurrentUser,
    PRODUCTION_READ_PERMISSIONS,
    is_admin,
    user_permissions,
)
from app.models import (
    Bundle,
    Department,
    Invoice,
    Notification,
    Package,
    ProductionOrder,
    Role,
    SalesOrder,
    Shipment,
    Task,
    User,
    WorkOrder,
)
from app.schemas.tasks import TaskIn, TaskUpdate, TaskOut, TaskPageOut
from app.services.audit import log_action
from app.services.notifications import notify
from app.services.user_access import access_configured, permission_denied
from app.services.factory_scope import (
    available_factory_codes,
    factory_for_department,
    require_factory_access,
    user_is_super_admin,
)
from app.services.packaging_scope import normalize_packaging_department_code, require_package_access

router = APIRouter(prefix="/tasks", tags=["tasks"])


_TASK_REFERENCE_MODELS = {
    "salesorder": SalesOrder,
    "productionorder": ProductionOrder,
    "workorder": WorkOrder,
    "bundle": Bundle,
    "package": Package,
    "shipment": Shipment,
    "invoice": Invoice,
}

_TASK_REFERENCE_ALIASES = {
    **{key: key for key in _TASK_REFERENCE_MODELS},
    "salesorders": "salesorder",
    "productionorders": "productionorder",
    "workorders": "workorder",
    "bundles": "bundle",
    "packages": "package",
    "shipments": "shipment",
    "invoices": "invoice",
}
_TASK_REFERENCE_PERMISSIONS = {
    # Keep task references aligned with each target's actual read endpoint.
    # Sales orders, bundles and shipments only require CurrentUser there.
    "productionorder": PRODUCTION_READ_PERMISSIONS,
    "workorder": PRODUCTION_READ_PERMISSIONS,
    "invoice": ("finance.view", "*"),
}


@dataclass(frozen=True)
class _TaskReferenceAccess:
    key: str
    entity_id: int
    row: object
    required_factory: str | None


def _normalize_task_entity_type(entity_type: str) -> str:
    token = entity_type.strip().casefold()
    if re.fullmatch(r"[a-z0-9_]+", token):
        compact = token.replace("_", "")
    elif re.fullmatch(r"[a-z0-9]+(?:[ -]+[a-z0-9]+)*", token):
        compact = re.sub(r"[ -]+", "", token)
    else:
        return token
    return _TASK_REFERENCE_ALIASES.get(compact, compact)


def _require_task_reference_permission(user: User, key: str) -> None:
    required = _TASK_REFERENCE_PERMISSIONS.get(key)
    if required is None:
        return
    granted = set(user_permissions(user))
    if granted.intersection(required):
        return
    raise HTTPException(403, "Not allowed to reference this task target")


def _task_reference_factory(key: str, row: object, db: DbSession) -> str | None:
    if key == "productionorder":
        order = row
    elif key == "workorder":
        order = _locked_task_reference(
            db,
            ProductionOrder,
            getattr(row, "production_order_id", None),
        )
        if order is None:
            raise HTTPException(409, "Task reference production order is missing")
    else:
        return None
    return "ECO" if order.source_type == "usluga" else None


def _locked_task_reference(db: DbSession, model, entity_id: int):
    """Keep a validated target stable until the task transaction commits."""
    return (
        db.query(model)
        .filter(model.id == entity_id)
        .with_for_update(read=True, key_share=True, of=model)
        .first()
    )


def _load_task_reference(
    entity_type: str | None,
    entity_id: int | None,
    db: DbSession,
    current: User,
    *,
    allow_legacy_missing: bool = False,
) -> _TaskReferenceAccess | None:
    """Resolve a new target and authorize the actor before it can be persisted.

    Existing unsupported or deleted references remain editable when the target
    fields themselves are unchanged. New and changed references are strict.
    """
    if entity_type is None or entity_id is None:
        return None
    key = _normalize_task_entity_type(entity_type)
    model = _TASK_REFERENCE_MODELS.get(key)
    if model is None:
        if allow_legacy_missing:
            return None
        raise HTTPException(422, f"Unsupported task reference type: {entity_type}")
    if not allow_legacy_missing:
        _require_task_reference_permission(current, key)
    row = _locked_task_reference(db, model, entity_id)
    if row is None:
        if allow_legacy_missing:
            return None
        raise HTTPException(404, "Task reference target not found")
    if allow_legacy_missing:
        _require_task_reference_permission(current, key)
    reference = _TaskReferenceAccess(
        key=key,
        entity_id=entity_id,
        row=row,
        required_factory=_task_reference_factory(key, row, db),
    )
    _require_actor_reference_access(current, reference)
    return reference


def _require_actor_reference_access(
    user: User,
    reference: _TaskReferenceAccess,
) -> None:
    if reference.key == "package":
        require_package_access(user, reference.row)
    elif reference.required_factory is not None:
        require_factory_access(user, reference.required_factory)


def _permissions_in_factory(user: User, factory: str) -> set[str]:
    # Simulate the exact permission dependency after logging in to this
    # factory. This matters for Super Admin: global role permissions continue
    # to apply in secondary factories, while that factory's explicit denials
    # still win.
    scoped_user = SimpleNamespace(
        role=user.role,
        department=user.department,
        factory_code=user.factory_code,
        extra_permissions=user.extra_permissions,
        access_policy=user.access_policy,
        session_factory_code=factory,
    )
    return set(user_permissions(scoped_user))


def _assignee_can_open_package(user: User, package: object) -> bool:
    if user_is_super_admin(user):
        return True
    department = getattr(user, "department", None)
    department_code = str(getattr(department, "code", "") or "").strip().upper()
    if factory_for_department(department_code) is None:
        # This is the intentional non-operational-department exception used by
        # require_package_access on the package detail endpoint.
        return True
    owner_code = normalize_packaging_department_code(
        getattr(package, "packaging_department_code", None)
    )
    owner_factory = factory_for_department(owner_code)
    return owner_factory in available_factory_codes(user)


def _require_assignee_reference_access(user: User, reference: _TaskReferenceAccess) -> None:
    if not user.is_active:
        raise HTTPException(422, "Assigned user cannot access the task reference")
    if reference.key == "package":
        if _assignee_can_open_package(user, reference.row):
            return
        raise HTTPException(422, "Assigned user cannot access the task reference")
    required = _TASK_REFERENCE_PERMISSIONS.get(reference.key)
    if required is None:
        return
    for factory in available_factory_codes(user):
        if reference.required_factory is not None and factory != reference.required_factory:
            continue
        if _permissions_in_factory(user, factory).intersection(required):
            return
    raise HTTPException(422, "Assigned user cannot access the task reference")


def _can_manage(user: User) -> bool:
    """Admins and Management can create / reassign / delete tasks for anyone."""
    if permission_denied(user, "tasks.manage"):
        return False
    if is_admin(user):
        return True
    if not access_configured(user) and user.role and user.role.name in ("Admin", "Management"):
        return True
    perms = user_permissions(user)
    return "tasks.manage" in perms or "management.approve" in perms


def _require_single_assignee(assigned: int | None, db: DbSession, current: User, is_manager: bool) -> User | None:
    if assigned != current.id and not is_manager:
        raise HTTPException(403, "Only managers can assign tasks to other users")
    user = db.get(User, assigned) if assigned is not None else None
    if assigned is not None and user is None:
        raise HTTPException(404, "Assigned user not found")
    return user


def _broadcast_recipient_query(db: DbSession):
    """Load at most the user fields needed by API02 recipient authorization."""
    return db.query(User).options(
        load_only(
            User.id,
            User.factory_code,
            User.extra_permissions,
            User.access_policy,
            User.is_active,
        ),
        joinedload(User.role).load_only(Role.name, Role.permissions),
        joinedload(User.department).load_only(Department.code),
    )


def _task_link(
    t: Task,
    db: DbSession | None = None,
    reference: _TaskReferenceAccess | None = None,
) -> str | None:
    """Build a frontend URL for a task notification when the task references
    a concrete entity. Returns None when no mapping exists."""
    et = _normalize_task_entity_type(t.entity_type) if t.entity_type else ""
    eid = t.entity_id
    if not eid:
        return None
    if et == "workorder":
        work_order = reference.row if reference is not None and reference.key == "workorder" else None
        if work_order is None and db is not None:
            with db.no_autoflush:
                work_order = db.get(WorkOrder, eid)
        operation = str(getattr(work_order, "operation", "") or "").strip().lower()
        if operation in {"cutting", "printing", "sewing", "packaging"}:
            return f"/work-orders/{eid}/{operation}"
        return None
    mapping = {
        "salesorder": f"/sales-orders/{eid}",
        "productionorder": f"/production-orders/{eid}",
        "bundle": f"/bundles/{eid}",
        "package": f"/packages/{eid}",
        "shipment": "/shipments",
        "invoice": "/finance",
    }
    return mapping.get(et)


@router.get("", response_model=list[TaskOut] | TaskPageOut)
def list_tasks(
    db: DbSession, current: CurrentUser,
    scope: str = "mine",  # mine | created | all (manager/admin only)
    status: str | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
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
    ordered = qry.order_by(Task.id.desc())
    if page is None and page_size is None:
        return ordered.all()
    effective_page = page or 1
    effective_page_size = page_size or 50
    total = int(qry.order_by(None).count())
    rows = (
        ordered
        .offset((effective_page - 1) * effective_page_size)
        .limit(effective_page_size)
        .all()
    )
    return {
        "rows": rows,
        "total": total,
        "page": effective_page,
        "page_size": effective_page_size,
        "has_more": effective_page * effective_page_size < total,
    }


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
    reference = _load_task_reference(payload.entity_type, payload.entity_id, db, current)
    is_manager = _can_manage(current)
    requested_assignee = payload.assigned_to

    # Special manager-only broadcast mode: assigned_to == -1 means "everyone".
    if requested_assignee == -1:
        if not is_manager:
            raise HTTPException(403, "Only managers can assign tasks to everyone")
        # Share the notification fan-out ceiling (ERP_MCP_MAX_BULK_RECIPIENTS,
        # clamped to 1..250). Reading cap+1 makes oversized broadcasts fail
        # before recipient policy checks or any task/notification/audit write.
        max_recipients = _max_bulk_recipients()
        targets = (
            _broadcast_recipient_query(db)
            .filter(User.is_active.is_(True))
            .order_by(User.id)
            .limit(max_recipients + 1)
            .all()
        )
        if not targets:
            raise HTTPException(404, "No active users found")
        if len(targets) > max_recipients:
            raise HTTPException(
                400,
                f"Recipient count exceeds ERP_MCP_MAX_BULK_RECIPIENTS={max_recipients}",
            )
        if reference is not None:
            try:
                for user in targets:
                    if user.id == current.id:
                        _require_actor_reference_access(current, reference)
                    else:
                        _require_assignee_reference_access(user, reference)
            except HTTPException as exc:
                raise HTTPException(
                    422,
                    "Task reference is not accessible to every broadcast recipient",
                ) from exc

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
            created.append(t)
            db.add(Notification(
                user_id=user.id,
                title=f"New task: {t.title}",
                message=(t.description or "")[:280],
                link=_task_link(t, reference=reference),
            ))

        # No per-recipient generated ID is needed until the audit below.
        # Flush once so PostgreSQL can batch task/notification inserts.
        db.flush()
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
    assignee = _require_single_assignee(assigned, db, current, is_manager)
    if reference is not None and assignee is not None and assignee.id != current.id:
        _require_assignee_reference_access(assignee, reference)

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
            link=_task_link(t, reference=reference),
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
    next_assignee_user: User | None = None
    if "assigned_to" in changes and changes["assigned_to"] != previous_assignee:
        next_assignee_user = _require_single_assignee(changes["assigned_to"], db, current, is_manager)
    reference: _TaskReferenceAccess | None = None
    if "entity_type" in changes or "entity_id" in changes:
        next_entity_type = changes.get("entity_type", t.entity_type)
        next_entity_id = changes.get("entity_id", t.entity_id)
        if (next_entity_type is None) != (next_entity_id is None):
            raise HTTPException(422, "entity_id and entity_type must be provided together")
        # Unchanged legacy orphan references remain editable; new/changed targets
        # must pass the same access policy as their read endpoint.
        reference_changed = (next_entity_type != t.entity_type or next_entity_id != t.entity_id)
        if reference_changed:
            reference = _load_task_reference(next_entity_type, next_entity_id, db, current)
        elif "assigned_to" in changes and changes["assigned_to"] != previous_assignee:
            reference = _load_task_reference(
                t.entity_type,
                t.entity_id,
                db,
                current,
                allow_legacy_missing=True,
            )
    elif "assigned_to" in changes and changes["assigned_to"] != previous_assignee:
        reference = _load_task_reference(
            t.entity_type,
            t.entity_id,
            db,
            current,
            allow_legacy_missing=True,
        )

    if reference is not None:
        next_assignee_id = changes.get("assigned_to", t.assigned_to)
        if next_assignee_id is not None and next_assignee_id != current.id:
            if next_assignee_user is None or next_assignee_user.id != next_assignee_id:
                next_assignee_user = db.get(User, next_assignee_id)
            if next_assignee_user is None:
                raise HTTPException(409, "Task assignee no longer exists")
            _require_assignee_reference_access(next_assignee_user, reference)
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
            link=_task_link(t, db=db, reference=reference),
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
            link=_task_link(t, db=db),
        )
    log_action(db, current, "complete", "Task", t.id)
    db.commit(); db.refresh(t)
    return t
