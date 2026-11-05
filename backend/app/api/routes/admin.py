from datetime import datetime, time

from pydantic import BaseModel
from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import (
    DbSession,
    CurrentUser,
    is_super_admin,
    require_permissions,
    require_super_admin,
    user_permissions,
)
from fastapi import Depends
from app.db.base import Base
from app.schemas import User, Department, AuditLog, Employee, WorkOrder
from app.libs.dto.catalog.catalog import (
    UserIn, UserUpdate, UserOut, RoleIn, RoleOut, DepartmentIn, DepartmentOut,
)
from app.models.audit_service import export_audit_hash_chain, log_action, verify_audit_hash_chain
from app.models.password_reset_service import send_password_email_safely
from app.db.reset_demo import reset_to_seed
from app.models.identity.users_service import (
    create_user as create_user_account, list_users as list_identity_users, get_user as get_identity_user,
    update_user as update_identity_user,
    _count_active_admins, _count_active_super_admins, _lock_active_user_memberships,
)
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


ACTION_LABELS = {
    "add_package": "added a package",
    "add_package_scan": "scanned and added a package",
    "add_ready_packages": "added ready packages",
    "admin_repair_totals": "repaired production totals",
    "approve": "approved",
    "approve_disposal": "approved disposal",
    "approve_planning": "approved planning",
    "block": "blocked",
    "bulk_create": "bulk created",
    "change_" + "password": "changed account credential",
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
    "mark_paid": "marked paid",
    "receive": "received",
    "receive_purchase_order_line": "received purchase order line",
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
    "update_status": "updated status",
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
    "PayrollAdjustment": "payroll adjustment",
    "PayrollPeriod": "payroll period",
    "PayrollRecord": "payroll record",
    "PrintingRecord": "printing record",
    "ProductionOrder": "production order",
    "PurchaseOrder": "purchase order",
    "PurchaseOrderLine": "purchase order line",
    "PurchaseRequest": "purchase request",
    "PurchaseRequestLine": "purchase request line",
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
@router.get("/access-catalog")
def access_catalog(current: User = Depends(require_permissions("admin.users", "*"))):
    return get_access_catalog(current)


@router.post("/users/access-preview")
def preview_user_access(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    return preview_identity_access(db, payload, current)









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
            "prev_hash": audit.prev_hash,
            "entry_hash": audit.entry_hash,
            "summary": summary,
            "root_cause_hint": root_cause_hint,
            "created_at": audit.created_at,
        }
        )
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out


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
