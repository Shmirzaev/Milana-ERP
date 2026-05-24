from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.core.deps import DbSession, CurrentUser, require_permissions
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


# ===== Users =====
def _require_strong_password(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    email = normalize_email(payload.email)
    _require_strong_password(payload.password)
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
    if "password" in data and data["password"]:
        _require_strong_password(data["password"])
        u.password_hash = hash_password(data.pop("password"))
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
    db.delete(u)
    log_action(db, current, "delete", "User", user_id)
    db.commit()


# ===== Roles =====
@router.get("/roles", response_model=list[RoleOut])
def list_roles(db: DbSession, _: CurrentUser):
    return db.query(Role).all()


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(payload: RoleIn, db: DbSession, current: User = Depends(require_permissions("*"))):
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
):
    qry = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    total = qry.count() if include_total else 0
    if include_total:
        safe_page = max(1, page)
        safe_size = max(1, min(page_size, 500))
        qry = qry.order_by(AuditLog.id.desc()).offset((safe_page - 1) * safe_size).limit(safe_size)
    else:
        qry = qry.order_by(AuditLog.id.desc()).limit(limit)
    rows = qry.all()
    out = [
        {
            "id": audit.id,
            "user_id": audit.user_id,
            "user_name": user.name if user else None,
            "user": {"id": user.id, "name": user.name} if user else None,
            "action": audit.action,
            "entity_type": audit.entity_type,
            "entity_id": audit.entity_id,
            "new_value": audit.new_value_json,
            "old_value": audit.old_value_json,
            "created_at": audit.created_at,
        }
        for audit, user in rows
    ]
    if include_total:
        return {"rows": out, "total": total, "page": max(1, page), "page_size": max(1, min(page_size, 500))}
    return out


@router.post("/admin/reset-test-data")
def reset_test_data(payload: ResetDemoIn, _: User = Depends(require_permissions("*"))):
    expected = "RESET MILANA ERP"
    if payload.confirm.strip().upper() != expected:
        raise HTTPException(400, f'Invalid confirmation. Send "{expected}" in confirm.')

    summary = reset_to_seed()
    return {"message": "System reset complete", **summary}
