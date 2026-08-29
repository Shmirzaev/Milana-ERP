from __future__ import annotations

from fastapi import HTTPException

FACTORY_CODES = ("MIL", "BST", "ECO")
FACTORY_LABELS = {"MIL": "Milana", "BST": "Besttex", "ECO": "Eco Cotton"}
FACTORY_PERMISSION_PREFIX = "factory:"
DEPARTMENT_FACTORIES = {
    "CUT": "MIL", "PRT": "MIL", "SEW": "MIL", "MIL": "MIL", "PKG": "MIL",
    "BST": "BST", "BPK": "BST",
    "ECT": "ECO", "ECO": "ECO", "ECP": "ECO",
}
CUTTING_DEPARTMENTS = {"MIL": "CUT", "ECO": "ECT"}
SEWING_DEPARTMENTS = {"MIL": "MIL", "BST": "BST", "ECO": "ECO"}
PACKAGING_DEPARTMENTS = {"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}


def normalize_factory_code(value: str | None, *, default: str | None = None) -> str:
    code = str(value or default or "").strip().upper()
    if code not in FACTORY_CODES:
        raise HTTPException(400, "Factory must be MIL, BST, or ECO")
    return code


def user_is_super_admin(user) -> bool:
    role = getattr(user, "role", None)
    role_name = str(getattr(role, "name", "") or "").strip().lower()
    permissions = set(getattr(role, "permissions", None) or []) | set(getattr(user, "extra_permissions", None) or [])
    return role_name == "super admin" or "admin.super" in permissions


def factory_permissions_for(user, factory_code: str) -> list[str]:
    code = normalize_factory_code(factory_code)
    prefix = f"{FACTORY_PERMISSION_PREFIX}{code}:"
    permissions: list[str] = []
    seen: set[str] = set()
    for value in getattr(user, "extra_permissions", None) or []:
        if not isinstance(value, str):
            continue
        token = value.strip()
        if not token.startswith(prefix):
            continue
        permission = token[len(prefix):].strip()
        if not permission or permission in seen:
            continue
        seen.add(permission)
        permissions.append(permission)
    return permissions


def is_factory_permission_token(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith(FACTORY_PERMISSION_PREFIX)


def assigned_factory_code(user) -> str:
    return normalize_factory_code(getattr(user, "factory_code", None), default="MIL")


def available_factory_codes(user) -> list[str]:
    if user_is_super_admin(user):
        return list(FACTORY_CODES)
    assigned = assigned_factory_code(user)
    return [
        code
        for code in FACTORY_CODES
        if code == assigned or factory_permissions_for(user, code)
    ]


def authorize_login_factory(user, requested: str | None) -> str:
    selected = normalize_factory_code(requested, default="MIL" if user_is_super_admin(user) else assigned_factory_code(user))
    if selected not in available_factory_codes(user):
        raise HTTPException(403, "This account is not assigned to the selected factory")
    return selected


def bind_session_factory(user, token_factory: str | None) -> str:
    selected = authorize_login_factory(user, token_factory)
    setattr(user, "session_factory_code", selected)
    return selected


def selected_factory_code(user) -> str:
    return normalize_factory_code(
        getattr(user, "session_factory_code", None),
        default="MIL" if user_is_super_admin(user) else assigned_factory_code(user),
    )


def require_factory_access(user, factory_code: str) -> str:
    requested = normalize_factory_code(factory_code)
    if requested != selected_factory_code(user):
        raise HTTPException(403, f"Log in to {FACTORY_LABELS[requested]} to access this operation")
    return requested


def factory_for_department(department_code: str | None) -> str | None:
    return DEPARTMENT_FACTORIES.get(str(department_code or "").strip().upper())


def require_operational_department_access(user, department_code: str | None) -> None:
    factory = factory_for_department(department_code)
    if factory:
        require_factory_access(user, factory)


def require_work_order_factory_access(user, db, work_order) -> None:
    from app.models import Department
    code = db.query(Department.code).filter(Department.id == work_order.department_id).scalar()
    require_operational_department_access(user, code)


def cutting_department_scope(user, requested: str | None) -> str:
    expected = CUTTING_DEPARTMENTS.get(selected_factory_code(user))
    if not expected:
        raise HTTPException(403, "Besttex does not have a cutting operation")
    code = str(requested or expected).strip().upper()
    if code not in {"CUT", "ECT"}:
        raise HTTPException(400, "Cutting department must be CUT or ECT")
    require_operational_department_access(user, code)
    return code


def sewing_department_scope(user, requested: str | None) -> str:
    expected = SEWING_DEPARTMENTS[selected_factory_code(user)]
    code = str(requested or expected).strip().upper()
    if code not in set(SEWING_DEPARTMENTS.values()):
        raise HTTPException(400, "Sewing factory must be MIL, BST, or ECO")
    require_operational_department_access(user, code)
    return code


def packaging_department_for_factory(factory_code: str) -> str:
    return PACKAGING_DEPARTMENTS[normalize_factory_code(factory_code)]


def enforce_request_factory_scope(user, request) -> None:
    path = str(request.url.path or "")
    query = request.query_params
    if path.endswith("/inbox") and query.get("dept"):
        require_operational_department_access(user, query.get("dept"))
    sewing = query.get("factory") or query.get("sewing_factory_code")
    if sewing and ("sewing" in path or "bundles" in path or "work-orders" in path):
        sewing_department_scope(user, sewing)
    cutting = query.get("cutting_department") or query.get("cutting_department_code")
    if cutting:
        cutting_department_scope(user, cutting)
    packaging = query.get("packaging_department") or query.get("packaging_department_code")
    if packaging:
        require_operational_department_access(user, packaging)
