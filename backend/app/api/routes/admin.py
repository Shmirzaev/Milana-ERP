from fastapi import APIRouter, HTTPException

from app.core.deps import DbSession, CurrentUser, require_permissions
from fastapi import Depends
from app.core.security import hash_password
from app.models import User, Role, Department, AuditLog
from app.schemas.catalog import (
    UserIn, UserUpdate, UserOut, RoleIn, RoleOut, DepartmentIn, DepartmentOut,
)
from app.services.audit import log_action

router = APIRouter(tags=["admin"])


# ===== Users =====
@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: User = Depends(require_permissions("admin.users", "*"))):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: DbSession, current: User = Depends(require_permissions("admin.users", "*"))):
    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(400, "Email already exists")
    u = User(
        name=payload.name,
        email=payload.email.lower(),
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
        u.password_hash = hash_password(data.pop("password"))
    elif "password" in data:
        data.pop("password")
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


# ===== Audit log =====
@router.get("/audit-logs")
def list_audit_logs(db: DbSession, _: User = Depends(require_permissions("admin.audit", "*")), limit: int = 200):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "new_value": r.new_value_json,
            "old_value": r.old_value_json,
            "created_at": r.created_at,
        }
        for r in rows
    ]
