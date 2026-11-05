"""Task creation, reference validation and system stock-shortage creation.

User creation owns its commit; Sales retains its outer transaction for shortages.
"""
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.deps import PRODUCTION_READ_PERMISSIONS, user_permissions, is_admin
from app.models.factory_scope_service import available_factory_codes, factory_for_department, require_factory_access, user_is_super_admin
from app.models.packaging_scope_service import normalize_packaging_department_code, require_package_access
from app.schemas import Bundle, Invoice, Package, ProductionOrder, SalesOrder, Shipment, Task, User, WorkOrder
from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.schemas.work_management.task_persistence import add_stock_shortage_task, add_created_task
from app.schemas.core_persistence import add_notification_row
from app.libs.dto.work_management.tasks import TaskIn
from app.models.audit_service import log_action
from app.models.notifications_service import _max_bulk_recipients
from app.models.user_access_service import access_configured, permission_denied


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


def _require_single_assignee(assigned: int | None, db: Session, current: User, is_manager: bool) -> None:
    if assigned != current.id and not is_manager:
        raise HTTPException(403, "Only managers can assign tasks to other users")
    if assigned is not None and not db.get(User, assigned):
        raise HTTPException(404, "Assigned user not found")


def _task_link(t: Task, db: Session | None = None, reference=None) -> str | None:
    """Build a frontend URL for a task notification when the task references
    a concrete entity. Returns None when no mapping exists."""
    et = task_reference_key(t.entity_type)
    eid = t.entity_id
    if not eid:
        return None
    if et == "workorder":
        work_order = reference.row if reference is not None and reference.key == et else None
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


def _creation_values(payload: TaskIn, created_by: int, assigned_to: int) -> dict:
    return dict(title=payload.title, description=payload.description,
                assigned_to=assigned_to, created_by=created_by,
                status=payload.status, priority=payload.priority,
                due_date=payload.due_date, entity_type=payload.entity_type,
                entity_id=payload.entity_id)


def create_task(payload: TaskIn, db: Session, current: User, *, audit=log_action) -> Task:
    reference = resolve_task_reference(db, current, payload.entity_type, payload.entity_id)
    is_manager = _can_manage(current)
    requested_assignee = payload.assigned_to

    # Special manager-only broadcast mode: assigned_to == -1 means "everyone".
    if requested_assignee == -1:
        if not is_manager:
            raise HTTPException(403, "Only managers can assign tasks to everyone")
        max_recipients = _max_bulk_recipients()
        targets = db.query(User.id).filter(User.is_active.is_(True)).order_by(User.id).limit(max_recipients + 1).all()
        if len(targets) > max_recipients:
            raise HTTPException(400, f"Recipient count exceeds ERP_MCP_MAX_BULK_RECIPIENTS={max_recipients}")
        if not targets:
            raise HTTPException(404, "No active users found")
        if reference:
            recipients = db.query(User).filter(User.id.in_([row.id for row in targets])).all()
            for user in recipients:
                if user.id != current.id:
                    require_assignee_reference_access(user, reference)

        created: list[Task] = []
        for user in targets:
            t = add_created_task(db, **_creation_values(payload, current.id, user.id))
            created.append(t)
            add_notification_row(db, user_id=user.id, title=f"New task: {t.title}",
                                 message=(t.description or "")[:280], link=_task_link(t, reference=reference))

        # No per-recipient generated ID is needed until the audit below.
        # Flush once so PostgreSQL can batch task/notification inserts.
        db.flush()
        first_task = created[0]
        audit(
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
    _require_single_assignee(assigned, db, current, is_manager)
    if reference and assigned != current.id:
        require_assignee_reference_access(db.get(User, assigned), reference)

    t = add_created_task(db, **_creation_values(payload, current.id, assigned))
    db.flush()

    # Notify the assignee unless they assigned to themselves.
    if assigned != current.id:
        add_notification_row(db, user_id=assigned, title=f"New task: {t.title}",
                             message=(t.description or "")[:280], link=_task_link(t, reference=reference))
        db.flush()

    audit(db, current, "create", "Task", t.id, new_value={"title": t.title, "assigned_to": assigned})
    db.commit()
    db.refresh(t)
    return t



_REFERENCE_MODELS = {
    "salesorder": SalesOrder,
    "productionorder": ProductionOrder,
    "workorder": WorkOrder,
    "bundle": Bundle,
    "package": Package,
    "shipment": Shipment,
    "invoice": Invoice,
}
_REFERENCE_PERMISSIONS = {
    "productionorder": PRODUCTION_READ_PERMISSIONS,
    "workorder": PRODUCTION_READ_PERMISSIONS,
    "invoice": ("finance.view", "*"),
}


@dataclass(frozen=True)
class TaskReference:
    key: str
    row: object
    factory: str | None


def task_reference_key(entity_type: str | None) -> str:
    token = str(entity_type or "").strip().casefold().replace("_", "").replace("-", "").replace(" ", "")
    return token[:-1] if token.endswith("s") and token[:-1] in _REFERENCE_MODELS else token


def _locked_row(db: Session, model, entity_id: int):
    return db.query(model).filter(model.id == entity_id).with_for_update(read=True, key_share=True, of=model).first()


def _reference_factory(db: Session, key: str, row: object) -> str | None:
    if key == "productionorder":
        order = row
    elif key in {"workorder", "bundle"}:
        order = _locked_row(db, ProductionOrder, row.production_order_id)
        if order is None:
            raise HTTPException(409, "Task reference production order is missing")
    else:
        return None
    return "ECO" if order.source_type == "usluga" else None


def resolve_task_reference(
    db: Session, current: User, entity_type: str | None, entity_id: int | None,
    *, allow_legacy_missing: bool = False,
) -> TaskReference | None:
    if entity_type is None or entity_id is None:
        return None
    key = task_reference_key(entity_type)
    model = _REFERENCE_MODELS.get(key)
    if model is None:
        if allow_legacy_missing:
            return None
        raise HTTPException(422, f"Unsupported task reference type: {entity_type}")
    required = _REFERENCE_PERMISSIONS.get(key)
    if required and not allow_legacy_missing and not set(user_permissions(current)).intersection(required):
        raise HTTPException(403, "Not allowed to reference this task target")
    row = _locked_row(db, model, entity_id)
    if row is None or (key == "shipment" and row.deleted_at is not None):
        if allow_legacy_missing:
            return None
        raise HTTPException(404, "Task reference target not found")
    if required and not set(user_permissions(current)).intersection(required):
        raise HTTPException(403, "Not allowed to reference this task target")
    reference = TaskReference(key, row, _reference_factory(db, key, row))
    if key == "package":
        require_package_access(current, row)
    elif reference.factory:
        require_factory_access(current, reference.factory)
    return reference


def _permissions_in_factory(user: User, factory: str) -> set[str]:
    scoped = SimpleNamespace(
        role=user.role, department=user.department, factory_code=user.factory_code,
        extra_permissions=user.extra_permissions, access_policy=user.access_policy,
        session_factory_code=factory,
    )
    return set(user_permissions(scoped))


def require_assignee_reference_access(user: User, reference: TaskReference) -> None:
    if not user.is_active:
        raise HTTPException(422, "Assigned user cannot access the task reference")
    if reference.key == "package":
        if user_is_super_admin(user):
            return
        department_code = str(getattr(user.department, "code", "") or "").strip().upper()
        if factory_for_department(department_code) is None:
            return
        owner = factory_for_department(normalize_packaging_department_code(reference.row.packaging_department_code))
        if owner in available_factory_codes(user):
            return
    else:
        required = _REFERENCE_PERMISSIONS.get(reference.key)
        for factory in available_factory_codes(user):
            if reference.factory and factory != reference.factory:
                continue
            if required is None or _permissions_in_factory(user, factory).intersection(required):
                return
    raise HTTPException(422, "Assigned user cannot access the task reference")


def validate_task_reference_update(
    db: Session, current: User, task, changes: dict, next_assignee: User | None,
) -> TaskReference | None:
    next_type = changes.get("entity_type", task.entity_type)
    next_id = changes.get("entity_id", task.entity_id)
    reference_fields_sent = "entity_type" in changes or "entity_id" in changes
    assignee_changed = "assigned_to" in changes and changes["assigned_to"] != task.assigned_to
    if not reference_fields_sent and not assignee_changed:
        return None
    if reference_fields_sent and (next_type is None) != (next_id is None):
        raise HTTPException(422, "entity_type and entity_id must be provided together")
    reference_changed = next_type != task.entity_type or next_id != task.entity_id
    if not reference_changed and not assignee_changed:
        return None
    if (next_type is None) != (next_id is None):
        return None  # Preserve unrelated reassignment of an existing legacy partial reference.
    reference = resolve_task_reference(db, current, next_type, next_id, allow_legacy_missing=not reference_changed)
    next_assignee_id = changes.get("assigned_to", task.assigned_to)
    if reference and next_assignee_id is not None and next_assignee is None:
        raise HTTPException(409, "Task assignee no longer exists")
    if reference and next_assignee and next_assignee.id != current.id:
        require_assignee_reference_access(next_assignee, reference)
    return reference


def create_stock_shortage_task(
    db: Session, *, title: str, description: str, assigned_to: int,
    created_by: int, due_date: datetime | None,
) -> None:
    add_stock_shortage_task(db, title=title, description=description,
                           assigned_to=assigned_to, created_by=created_by, due_date=due_date,
                           status=TaskStatus.PENDING, priority=TaskPriority.HIGH)
