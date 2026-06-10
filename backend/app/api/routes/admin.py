from datetime import datetime, time, timezone

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from fastapi import Depends
from app.core.security import hash_password, normalize_email, validate_password_strength
from app.models import User, Role, Department, AuditLog, Employee, WorkOrder
from app.schemas.catalog import (
    UserIn, UserUpdate, UserOut, RoleIn, RoleOut, DepartmentIn, DepartmentOut,
)
from app.services.audit import log_action
from app.db.reset_demo import reset_to_seed

router = APIRouter(tags=["admin"])


class ResetDemoIn(BaseModel):
    confirm: str


ACTION_LABELS = {
    "add_package": "added a package",
    "add_package_scan": "scanned and added a package",
    "add_ready_packages": "added ready packages",
    "admin_repair_totals": "repaired production totals",
    "approve": "approved",
    "approve_disposal": "approved disposal",
    "approve_planning": "approved planning",
    "block": "blocked",
    "change_password": "changed password",  # nosec B105 - audit action label, not a credential.
    "complete": "completed",
    "confirm": "confirmed",
    "create": "created",
    "create_work_orders": "created work orders",
    "delete": "deleted",
    "delivered": "marked delivered",
    "deliver": "marked delivered",
    "damaged": "marked damaged",
    "generate_invoice": "generated invoice",
    "mark_disposed": "marked disposed",
    "mark_shipped": "marked shipped",
    "receive": "received",
    "receive_at_printing": "received at printing",
    "receive_at_sewing": "received at sewing",
    "receive_storage": "received in storage",
    "reject_disposal": "rejected disposal",
    "release_reservation": "released reservation",
    "request_disposal": "requested disposal",
    "reserve": "reserved",
    "reserve_stock": "reserved stock",
    "sell": "sold",
    "send_to_printing": "sent to printing",
    "send_to_sewing": "sent to sewing",
    "ship": "shipped",
    "start": "started",
    "transfer": "transferred",
    "unblock": "unblocked",
    "update": "updated",
    "update_profile": "updated profile",
    "upload_logo": "uploaded logo",
}

ENTITY_LABELS = {
    "Brand": "brand",
    "Bundle": "bundle",
    "Collection": "collection",
    "Customer": "customer",
    "CuttingRecord": "cutting record",
    "Department": "department",
    "Employee": "employee",
    "FinishedGoodsStock": "finished goods stock",
    "Invoice": "invoice",
    "Item": "inventory item",
    "Model": "model",
    "ModelBOM": "model BOM",
    "ModelImage": "model image",
    "ModelSize": "model size",
    "Package": "package",
    "Payment": "payment",
    "PrintingRecord": "printing record",
    "ProductionOrder": "production order",
    "QualityCheck": "quality check",
    "SalesOrder": "sales order",
    "SewingAssignment": "sewing assignment",
    "SewingFlow": "sewing flow",
    "SewingRecord": "sewing record",
    "Shipment": "shipment",
    "StockBatch": "stock batch",
    "StockMovement": "stock movement",
    "StockReservation": "stock reservation",
    "Supplier": "supplier",
    "SystemSetting": "system setting",
    "Task": "task",
    "User": "user",
    "Warehouse": "warehouse",
    "WasteDisposalRequest": "waste disposal request",
    "WasteRecord": "waste record",
    "WorkOrder": "work order",
}

DETAIL_KEYS = (
    "order_no",
    "production_no",
    "work_order_no",
    "bundle_no",
    "package_no",
    "shipment_no",
    "invoice_no",
    "batch_no",
    "sku",
    "code",
    "name",
    "title",
    "full_name",
    "email",
)


def _sentence(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _label_action(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace("_", " "))


def _label_entity(entity_type: str) -> str:
    return ENTITY_LABELS.get(entity_type, entity_type.replace("_", " ").lower())


def _pick_identifier(value: dict | None) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in DETAIL_KEYS:
        raw = value.get(key)
        if raw not in (None, ""):
            return str(raw)
    return None


def _changed_fields(old_value: dict | None, new_value: dict | None) -> list[dict]:
    old = old_value if isinstance(old_value, dict) else {}
    new = new_value if isinstance(new_value, dict) else {}
    keys = sorted(set(old.keys()) | set(new.keys()))
    changes = []
    for key in keys:
        before = old.get(key)
        after = new.get(key)
        if before == after and key in old and key in new:
            continue
        changes.append({"field": key, "from": before, "to": after})
    return changes


def _audit_summary(audit: AuditLog, user: User | None) -> tuple[str, str]:
    actor = user.name if user else "System"
    action = _label_action(audit.action)
    entity = _label_entity(audit.entity_type)
    identifier = _pick_identifier(audit.new_value_json) or _pick_identifier(audit.old_value_json)
    target = f"{entity} #{audit.entity_id}" if audit.entity_id is not None else entity
    if identifier:
        target = f"{target} ({identifier})"
    summary = _sentence(f"{actor} {action} {target}.")
    reason = "Check this event and nearby earlier events when investigating the root cause."
    changes = _changed_fields(audit.old_value_json, audit.new_value_json)
    if changes:
        names = ", ".join(c["field"].replace("_", " ") for c in changes[:4])
        if len(changes) > 4:
            names += f", plus {len(changes) - 4} more"
        reason = f"Changed fields: {names}."
    return summary, reason


def _parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if "T" in value:
            return datetime.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
        if end_of_day:
            return datetime.combine(parsed.date(), time.max)
        return datetime.combine(parsed.date(), time.min)
    except ValueError as e:
        raise HTTPException(400, f"Invalid date filter: {value}") from e


# ===== Users =====
def _require_strong_password(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _assert_can_grant_role(db: DbSession, actor: User, role_id: int | None) -> None:
    """Prevent privilege escalation: a user-manager may only assign a role whose
    permissions are a subset of their own. Holding '*' allows granting anything.
    Without this guard, anyone with 'admin.users' could mint or self-assign an
    admin ('*') role and take over the system."""
    actor_perms = set(user_permissions(actor))
    if "*" in actor_perms:
        return
    if role_id is None:
        return
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    target_perms = set(role.permissions or [])
    if "*" in target_perms:
        raise HTTPException(403, "You cannot assign an administrator role")
    missing = target_perms - actor_perms
    if missing:
        raise HTTPException(403, f"You cannot grant permissions you don't hold: {sorted(missing)}")


def _count_active_admins(db: DbSession, exclude_user_id: int | None = None) -> int:
    count = 0
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if exclude_user_id is not None and u.id == exclude_user_id:
            continue
        if "*" in user_permissions(u):
            count += 1
    return count


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    email = normalize_email(payload.email)
    _require_strong_password(payload.password)
    _assert_can_grant_role(db, current, payload.role_id)
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "Email already exists")
    u = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(payload.password),
        role_id=payload.role_id,
        department_id=payload.department_id,
        is_active=payload.is_active,
    )
    db.add(u)
    db.flush()
    log_action(db, current, "create", "User", u.id, new_value={"email": u.email})
    db.commit()
    db.refresh(u)
    return u


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    actor_is_admin = "*" in user_permissions(current)
    # Guard against self-escalation and self-lockout by a non-superadmin manager.
    if u.id == current.id and not actor_is_admin:
        if "role_id" in data and data["role_id"] != u.role_id:
            raise HTTPException(403, "You cannot change your own role")
        if data.get("is_active") is False:
            raise HTTPException(403, "You cannot deactivate your own account")
    # A role change may only grant permissions the actor already holds.
    if "role_id" in data and data["role_id"] != u.role_id:
        _assert_can_grant_role(db, current, data["role_id"])
    # Never let the last active administrator be demoted or deactivated.
    demoting_admin = "role_id" in data and data["role_id"] != u.role_id and "*" in (user_permissions(u))
    deactivating = data.get("is_active") is False and u.is_active
    if (demoting_admin or deactivating) and "*" in user_permissions(u) and _count_active_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot remove the last active administrator")
    if "password" in data and data["password"]:
        _require_strong_password(data["password"])
        u.password_hash = hash_password(data.pop("password"))
        u.tokens_valid_from = datetime.now(timezone.utc)
    elif "password" in data:
        data.pop("password")
    if "email" in data and data["email"]:
        data["email"] = normalize_email(data["email"])
    for k, v in data.items():
        setattr(u, k, v)
    log_action(db, current, "update", "User", u.id, new_value=data)
    db.commit()
    db.refresh(u)
    return u


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == current.id:
        raise HTTPException(400, "You cannot delete your own account")
    if "*" in user_permissions(u) and _count_active_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot delete the last active administrator")
    db.delete(u)
    log_action(db, current, "delete", "User", user_id)
    db.commit()


# ===== Roles =====
@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession, _: CurrentUser):
    return db.query(Role).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleIn, db: DbSession, current: User = Depends(require_permissions("*"))):
    # Already restricted to superadmins ('*'), so any permission set is allowed.
    r = Role(name=payload.name, permissions=payload.permissions)
    db.add(r)
    db.flush()
    log_action(db, current, "create", "Role", r.id, new_value={"name": r.name})
    db.commit()
    db.refresh(r)
    return r


# ===== Departments =====
@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: DbSession, _: CurrentUser):
    return db.query(Department).order_by(Department.id).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentIn, db: DbSession, current: User = Depends(require_permissions("*"))):
    d = Department(name=payload.name, code=payload.code)
    db.add(d)
    db.flush()
    log_action(db, current, "create", "Department", d.id, new_value={"name": d.name})
    db.commit()
    db.refresh(d)
    return d


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    payload: DepartmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    d = db.get(Department, department_id)
    if not d:
        raise HTTPException(404, "Department not found")

    name = payload.name.strip()
    code = payload.code.strip().upper()
    if not name or not code:
        raise HTTPException(400, "name and code are required")

    name_exists = db.query(Department).filter(Department.name == name, Department.id != department_id).first()
    if name_exists:
        raise HTTPException(400, "Department name already exists")
    code_exists = db.query(Department).filter(Department.code == code, Department.id != department_id).first()
    if code_exists:
        raise HTTPException(400, "Department code already exists")

    old = {"name": d.name, "code": d.code}
    d.name = name
    d.code = code
    log_action(db, current, "update", "Department", d.id, old_value=old, new_value={"name": d.name, "code": d.code})
    db.commit()
    db.refresh(d)
    return d


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(
    department_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    d = db.get(Department, department_id)
    if not d:
        raise HTTPException(404, "Department not found")

    if db.query(User).filter(User.department_id == department_id).first():
        raise HTTPException(409, "Department is assigned to users. Reassign users before delete.")
    if db.query(Employee).filter(Employee.department_id == department_id).first():
        raise HTTPException(409, "Department is assigned to employees. Reassign employees before delete.")
    if db.query(WorkOrder).filter(WorkOrder.department_id == department_id).first():
        raise HTTPException(409, "Department is used by work orders. Delete is blocked.")

    db.delete(d)
    log_action(db, current, "delete", "Department", department_id)
    db.commit()


# ===== Audit log =====
@router.get("/audit-logs")
def list_audit_logs(
    db: DbSession,
    _: User = Depends(require_permissions("admin.audit", "*")),
    limit: int = 200,
    page: int = 1,
    page_size: int = 50,
    include_total: bool = False,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
):
    qry = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    if user_id:
        qry = qry.filter(AuditLog.user_id == user_id)
    if entity_type:
        qry = qry.filter(AuditLog.entity_type == entity_type.strip())
    if entity_id is not None:
        qry = qry.filter(AuditLog.entity_id == entity_id)
    if action:
        qry = qry.filter(AuditLog.action == action.strip())
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to, end_of_day=True)
    if parsed_from:
        qry = qry.filter(AuditLog.created_at >= parsed_from)
    if parsed_to:
        qry = qry.filter(AuditLog.created_at <= parsed_to)
    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        qry = qry.filter(
            (AuditLog.action.ilike(like))
            | (AuditLog.entity_type.ilike(like))
            | (User.name.ilike(like))
            | (User.email.ilike(like))
        )
    total = qry.count() if include_total else 0
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.order_by(AuditLog.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size)
    else:
        qry = qry.order_by(AuditLog.id.desc()).limit(limit)
    rows = qry.all()
    out = []
    for audit, user in rows:
        summary, root_cause_hint = _audit_summary(audit, user)
        out.append(
            {
            "id": audit.id,
            "user_id": audit.user_id,
            "user_name": user.name if user else None,
            "user": {"id": user.id, "name": user.name, "email": user.email} if user else None,
            "action": audit.action,
            "action_label": _label_action(audit.action),
            "entity_type": audit.entity_type,
            "entity_label": _label_entity(audit.entity_type),
            "entity_id": audit.entity_id,
            "new_value": audit.new_value_json,
            "old_value": audit.old_value_json,
            "changed_fields": _changed_fields(audit.old_value_json, audit.new_value_json),
            "summary": summary,
            "root_cause_hint": root_cause_hint,
            "created_at": audit.created_at,
        }
        )
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out


@router.post("/admin/reset-test-data")
def reset_test_data(payload: ResetDemoIn, _: User = Depends(require_permissions("*"))):
    if settings.is_production or not settings.ALLOW_DEMO_RESET:
        raise HTTPException(403, "Demo reset is disabled")
    expected = "RESET MILANA ERP"
    if payload.confirm.strip().upper() != expected:
        raise HTTPException(400, f'Invalid confirmation. Send "{expected}" in confirm.')

    summary = reset_to_seed()
    return {"message": "System reset complete", **summary}
