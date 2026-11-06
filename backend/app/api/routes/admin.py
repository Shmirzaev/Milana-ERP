from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import (
    SUPER_ADMIN_PERMISSION,
    DbSession,
    CurrentUser,
    is_super_admin,
    normalize_permissions,
    require_permissions,
    require_super_admin,
    user_permissions,
)
from fastapi import Depends
from app.core.security import normalize_email
from app.db.base import Base
from app.schemas import User, Department, AuditLog
from app.models.factory_scope_service import normalize_factory_code
from app.libs.dto.catalog.catalog import (
    UserIn, UserUpdate, UserOut, RoleIn, RoleOut, DepartmentIn, DepartmentOut,
)
from app.models.people import departments_service
from app.models.credentials_service import apply_password_credential_change, lock_user_for_credential_change
from app.models import audit_service
from app.models.audit_service import (
    ACTION_LABELS as ACTION_LABELS,
    DETAIL_KEYS as DETAIL_KEYS,
    ENTITY_LABELS as ENTITY_LABELS,
    _audit_summary as _audit_summary,
    _changed_fields as _changed_fields,
    _label_action as _label_action,
    _label_entity as _label_entity,
    _parse_date as _parse_date,
    _pick_identifier as _pick_identifier,
    _sentence as _sentence,
)
from app.models.audit_service import export_audit_hash_chain, log_action, verify_audit_hash_chain
from app.models.password_reset_service import send_password_email_safely
from app.db.reset_demo import reset_to_seed
from app.core.permission_catalog import PERMISSION_CATALOG, PERMISSION_KEYS
from app.models.factory_scope_service import FACTORY_CODES, available_factory_codes
from app.models.identity.users_service import create_user as create_user_account, require_strong_password as _require_strong_password
from app.models.identity.access_service import (
    _access_subject, _user_access_values, _assert_policy_change,
    _assert_can_grant_role, _assert_can_grant_permissions,
)

from app.models.identity.roles_service import (
    list_roles as list_identity_roles, create_role as create_identity_role,
)

router = APIRouter(tags=["admin"])


class ResetDemoIn(BaseModel):
    confirm: str


MCP_READ_TOOLS = [
    {"name": "erp_me", "description": "Current authenticated ERP user and permissions."},
    {"name": "erp_gm_summary", "description": "GM management dashboard summary."},
    {"name": "erp_search", "description": "Global ERP search with sensitive field redaction."},
    {"name": "erp_active_production", "description": "Active production dashboard status."},
    {"name": "erp_late_orders", "description": "Late active orders derived from production dashboard data."},
    {"name": "erp_inventory_status", "description": "Inventory dashboard summary."},
    {"name": "erp_finance_summary", "description": "Finance dashboard summary when ERP permissions allow it."},
    {"name": "erp_list_employee_tasks", "description": "Task list with safe filters."},
]

MCP_WRITE_TOOLS = [
    {"name": "erp_send_notification", "description": "Confirmed notification send only."},
    {"name": "erp_create_task", "description": "Confirmed task creation only."},
]

MCP_BLOCKED_ACTIONS = [
    "edit or delete ERP records",
    "approve or reject production, shipment, finance, or payroll records",
    "change payroll or finance records",
    "change inventory or shipment records",
    "change production approvals",
    "change user permissions",
    "mutate raw database records",
]




















# ===== Users =====
@router.get("/access-catalog")
def access_catalog(current: User = Depends(require_permissions("admin.users", "*"))):
    own = set(user_permissions(current))
    return [{**row, "grantable": is_super_admin(current) if row["key"] in {"*", SUPER_ADMIN_PERMISSION}
             else "*" in own or row["key"] in own} for row in PERMISSION_CATALOG]


@router.post("/users/access-preview")
def preview_user_access(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    values = payload.model_dump(exclude={"password"})
    subject = _access_subject(db, values)
    available = available_factory_codes(subject)
    result = {}
    for factory in FACTORY_CODES:
        subject.session_factory_code = factory
        effective = user_permissions(subject)
        expanded = sorted((set(effective) - {"*"}) | (PERMISSION_KEYS - {"*", SUPER_ADMIN_PERMISSION} if "*" in effective else set()))
        result[factory] = {"permissions": effective, "effective": sorted(set(expanded) | ({"*"} if "*" in effective else set())), "available": factory in available}
    return result


def _count_active_admins(db: DbSession, exclude_user_id: int | None = None) -> int:
    count = 0
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if exclude_user_id is not None and u.id == exclude_user_id:
            continue
        if "*" in user_permissions(u):
            count += 1
    return count


def _count_active_super_admins(db: DbSession, exclude_user_id: int | None = None) -> int:
    count = 0
    for u in db.query(User).filter(User.is_active.is_(True)).all():
        if exclude_user_id is not None and u.id == exclude_user_id:
            continue
        if is_super_admin(u):
            count += 1
    return count


def _lock_active_user_memberships(db: DbSession) -> None:
    """Serialize changes that can remove the final administrator membership."""
    # NO KEY UPDATE still serializes membership mutations while allowing the
    # KEY SHARE lock used by a concurrent audit-log foreign-key insertion.
    # SQLite ignores the lock clause in disposable tests.
    db.query(User).filter(User.is_active.is_(True)).order_by(User.id).with_for_update(
        of=User, key_share=True
    ).populate_existing().all()



def _assert_user_has_no_audit_history(db: DbSession, user_id: int) -> None:
    if db.query(AuditLog.id).filter(AuditLog.user_id == user_id).first() is not None:
        raise HTTPException(409, "User has audit history. Deactivate the account instead.")


def _detach_user_references(db: DbSession, user_id: int) -> None:
    """Remove references that would otherwise block deleting a user account."""
    users_table = User.__table__
    for table in Base.metadata.sorted_tables:
        # Audit actors are part of the hash payload and must never be rewritten.
        if table is users_table or table is AuditLog.__table__:
            continue
        for column in table.c:
            if not any(fk.column.table is users_table and fk.column.name == "id" for fk in column.foreign_keys):
                continue
            if column.nullable:
                db.execute(update(table).where(column == user_id).values({column.name: None}))
            else:
                db.execute(delete(table).where(column == user_id))


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserIn,
    db: DbSession,
    background_tasks: BackgroundTasks,
    current: User = Depends(require_permissions("admin.users", "*")),
):
    u, setup_url = create_user_account(db, payload, current)
    if setup_url:
        background_tasks.add_task(send_password_email_safely, u.email, u.name, setup_url, u.id, "setup")
    return u


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    # Lock memberships in stable order before taking a target credential lock.
    if {"role_id", "extra_permissions", "access_policy", "is_active", "factory_code"} & payload.model_fields_set:
        _lock_active_user_memberships(db)
    credential_change = bool(payload.password)
    u = (
        lock_user_for_credential_change(db, user_id, require_active=False)
        if credential_change
        else db.get(User, user_id)
    )
    if not u:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    old_access = _user_access_values(u)
    actor_is_super_admin = is_super_admin(current)
    if "factory_code" in data:
        data["factory_code"] = normalize_factory_code(data["factory_code"])
        if not actor_is_super_admin and data["factory_code"] != u.factory_code:
            raise HTTPException(403, "Only Super Admin can change a user's factory")
        if data["factory_code"] != u.factory_code:
            u.tokens_valid_from = datetime.now(timezone.utc)
    if "extra_permissions" in data:
        data["extra_permissions"] = normalize_permissions(data["extra_permissions"])
    # Guard against self-escalation and self-lockout by a non-superadmin manager.
    if u.id == current.id and not actor_is_super_admin:
        if "role_id" in data and data["role_id"] != u.role_id:
            raise HTTPException(403, "You cannot change your own role")
        if "extra_permissions" in data and set(data["extra_permissions"]) != set(normalize_permissions(u.extra_permissions)):
            raise HTTPException(403, "You cannot change your own additional access")
        if data.get("is_active") is False:
            raise HTTPException(403, "You cannot deactivate your own account")
        if "access_policy" in data and (data["access_policy"] or {}) != (u.access_policy or {}):
            raise HTTPException(403, "You cannot change your own access")
    # A role change may only grant permissions the actor already holds.
    if "role_id" in data and data["role_id"] != u.role_id:
        _assert_can_grant_role(db, current, data["role_id"])
    if "extra_permissions" in data:
        _assert_can_grant_permissions(current, data["extra_permissions"], previous=u.extra_permissions)
    # Never let the last active administrator be demoted or deactivated.
    was_admin = "*" in user_permissions(u)
    was_super_admin = is_super_admin(u)
    future_subject = _assert_policy_change(db, current, {**old_access, **data}, old_access)
    future_permissions = user_permissions(future_subject)
    future_admin = "*" in future_permissions
    future_super_admin = is_super_admin(future_subject)
    if u.id != current.id and (was_admin or future_admin or was_super_admin or future_super_admin) and not actor_is_super_admin:
        raise HTTPException(403, "Only a super admin can manage administrator accounts")
    demoting_admin = was_admin and not future_admin
    demoting_super_admin = was_super_admin and not future_super_admin
    deactivating = data.get("is_active") is False and u.is_active
    if (demoting_super_admin or deactivating) and was_super_admin and _count_active_super_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot remove the last active super administrator")
    if (demoting_admin or deactivating) and was_admin and _count_active_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot remove the last active administrator")
    if "password" in data and data["password"]:
        _require_strong_password(data["password"])
    if "email" in data and data["email"]:
        data["email"] = normalize_email(data["email"])
    if data.get("name") is not None and len(data["name"]) > 128:
        raise HTTPException(422, "User name must be at most 128 characters")
    if data.get("email") is not None and len(data["email"]) > 255:
        raise HTTPException(422, "User email must be at most 255 characters")
    if "password" in data and data["password"]:
        apply_password_credential_change(db, u, data.pop("password"))
    elif "password" in data:
        data.pop("password")
    for k, v in data.items():
        setattr(u, k, v)
    audit_new_value = dict(data)
    if credential_change:
        audit_new_value.update({"credential_changed": True, "reset_links_invalidated": True})
    log_action(db, current, "update", "User", u.id, old_value=old_access, new_value=audit_new_value)
    db.commit()
    db.refresh(u)
    return u


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    _lock_active_user_memberships(db)
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == current.id:
        raise HTTPException(400, "You cannot delete your own account")
    if ("*" in user_permissions(u) or is_super_admin(u)) and not is_super_admin(current):
        raise HTTPException(403, "Only a super admin can delete administrator accounts")
    if is_super_admin(u) and _count_active_super_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot delete the last active super administrator")
    if "*" in user_permissions(u) and _count_active_admins(db, exclude_user_id=u.id) == 0:
        raise HTTPException(400, "Cannot delete the last active administrator")
    _assert_user_has_no_audit_history(db, user_id)
    try:
        _detach_user_references(db, user_id)
        db.delete(u)
        log_action(db, current, "delete", "User", user_id)
        db.commit()
    except IntegrityError:
        # A concurrent audit can appear after the guard. Its FK blocks deletion;
        # roll back all reference cleanup before checking the committed history.
        db.rollback()
        _assert_user_has_no_audit_history(db, user_id)
        raise


# ===== Roles =====
@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession, _: CurrentUser):
    return list_identity_roles(db)


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleIn, db: DbSession, current: User = Depends(require_permissions("*"))):
    return create_identity_role(db, payload, current)


# ===== Departments =====
@router.get("/departments", response_model=list[DepartmentOut])
def list_departments(db: DbSession, _: CurrentUser):
    return db.query(Department).order_by(Department.id).all()


@router.post("/departments", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentIn, db: DbSession, current: User = Depends(require_permissions("*"))):
    return departments_service.create_department(payload, db, current)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: int,
    payload: DepartmentIn,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    return departments_service.update_department(department_id, payload, db, current)


@router.delete("/departments/{department_id}", status_code=204)
def delete_department(
    department_id: int,
    db: DbSession,
    current: User = Depends(require_permissions("*")),
):
    departments_service.delete_department(department_id, db, current)


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
    return audit_service.list_audit_logs(
        db, limit=limit, page=page, page_size=page_size, include_total=include_total,
        user_id=user_id, entity_type=entity_type, entity_id=entity_id, action=action,
        date_from=date_from, date_to=date_to, q=q,
    )


@router.get("/audit-logs/hash-chain/export")
def export_audit_hash_chain_endpoint(
    db: DbSession,
    _: User = Depends(require_permissions("admin.audit", "*")),
    start_id: int | None = None,
    limit: int = 1000,
):
    return {
        "rows": export_audit_hash_chain(db, start_id=start_id, limit=limit),
        "start_id": start_id,
        "limit": max(1, min(int(limit or 1000), 5000)),
    }


@router.get("/audit-logs/hash-chain/verify")
def verify_audit_hash_chain_endpoint(
    db: DbSession,
    _: User = Depends(require_permissions("admin.audit", "*")),
    start_id: int | None = None,
    limit: int | None = None,
):
    return verify_audit_hash_chain(db, start_id=start_id, limit=limit)


@router.get("/admin/mcp-info")
def mcp_info(_: User = Depends(require_super_admin)):
    public_base_url = (settings.ERP_PUBLIC_BASE_URL or "https://erp.milanapremium.uz").strip().rstrip("/")
    return {
        "server_name": "milana-erp",
        "display_name": "Milana ERP AI GM Assistant",
        "erp_api_base_url": public_base_url,
        "transport": "stdio",
        "python_module": "milana_erp_mcp.server",
        "package_name": "milana-erp-mcp",
        "section_access": "Super Admin only",
        "runtime_access": "GM/Admin ERP bearer token required; MCP tools still use ERP API permissions.",
        "env": {
            "ERP_API_BASE_URL": public_base_url,
            "ERP_MCP_AUTH_MODE": "bearer",
            "ERP_MCP_BEARER_TOKEN": "REPLACE_WITH_REAL_ERP_TOKEN",
            "ERP_MCP_REQUIRE_CONFIRMATION": "true",
            "ERP_MCP_MAX_BULK_RECIPIENTS": "25",
        },
        "claude_desktop_config": {
            "mcpServers": {
                "milana-erp": {
                    "command": "python",
                    "args": ["-m", "milana_erp_mcp.server"],
                    "env": {
                        "ERP_API_BASE_URL": public_base_url,
                        "ERP_MCP_BEARER_TOKEN": "REPLACE_WITH_REAL_ERP_TOKEN",
                        "ERP_MCP_REQUIRE_CONFIRMATION": "true",
                    },
                },
            },
        },
        "read_tools": MCP_READ_TOOLS,
        "write_tools": MCP_WRITE_TOOLS,
        "blocked_actions": MCP_BLOCKED_ACTIONS,
        "security_notes": [
            "This page does not issue or display bearer tokens.",
            "The MCP server never connects directly to the ERP database.",
            "Write tools require explicit confirmation before calling the ERP API.",
            "Notification and task writes go through existing ERP endpoints and audit behavior.",
            "Send-to-everyone is intentionally not supported in v1.",
        ],
    }


@router.post("/admin/reset-test-data")
def reset_test_data(payload: ResetDemoIn, _: User = Depends(require_permissions("*"))):
    if settings.is_production or not settings.ALLOW_DEMO_RESET:
        raise HTTPException(403, "Demo reset is disabled")
    expected = "RESET MILANA ERP"
    if payload.confirm.strip().upper() != expected:
        raise HTTPException(400, f'Invalid confirmation. Send "{expected}" in confirm.')

    summary = reset_to_seed()
    return {"message": "System reset complete", **summary}
