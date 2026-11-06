from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.config import settings
from app.core.deps import (
    DbSession,
    CurrentUser,
    require_permissions,
    require_super_admin,
)
from fastapi import Depends
from app.schemas import User, Department
from app.libs.dto.catalog.catalog import (
    UserIn, UserUpdate, UserOut, RoleIn, RoleOut, DepartmentIn, DepartmentOut,
)
from app.models.people import departments_service
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
from app.models.audit_service import export_audit_hash_chain, verify_audit_hash_chain
from app.models.password_reset_service import send_password_email_safely
from app.db.reset_demo import reset_to_seed
from app.models.identity.users_service import create_user as create_user_account, list_users as list_identity_users, get_user as get_identity_user, update_user as update_identity_user, delete_user as delete_identity_user
from app.models.identity.access_service import (
    get_access_catalog, preview_user_access as preview_identity_access,
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
def access_catalog(db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    return get_access_catalog(db, current)


@router.post("/users/access-preview")
def preview_user_access(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    return preview_identity_access(db, payload, current)


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    return list_identity_users(db, _)


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
    return get_identity_user(db, user_id, _)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    return update_identity_user(db, user_id, payload, current)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    return delete_identity_user(db, user_id, current)


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
