from fastapi import APIRouter, HTTPException, Depends

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.models import Employee, User
from app.services.audit import log_action
from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class EmployeeIn(BaseModel):
    user_id: Optional[int] = None
    full_name: str
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
    status: str = "active"
    joined_at: Optional[datetime] = None


class EmployeeUpdate(BaseModel):
    """All fields optional so the client can send partial updates."""
    user_id: Optional[int] = None
    full_name: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
    status: Optional[str] = None
    joined_at: Optional[datetime] = None


router = APIRouter(tags=["hr"])


def _can_view_private_employee_fields(user: User) -> bool:
    perms = user_permissions(user)
    return "*" in perms or "hr.employees" in perms


def _serialize(r: Employee, *, include_private: bool = False) -> dict:
    payload = {
        "id": r.id, "user_id": r.user_id, "full_name": r.full_name,
        "department_id": r.department_id, "position": r.position,
        "status": r.status, "joined_at": r.joined_at,
    }
    if include_private:
        payload["phone"] = r.phone
        payload["salary"] = float(r.salary) if r.salary else None
    return payload


def _backfill_employees_from_users(db: DbSession) -> int:
    """Ensure each app user has a corresponding employee row.

    Older databases may contain demo users in `users` without entries in
    `employees`, which makes the HR table appear empty.
    """
    existing_user_ids = {
        uid
        for (uid,) in db.query(Employee.user_id).filter(Employee.user_id.isnot(None)).all()
        if uid is not None
    }
    users = db.query(User).order_by(User.id.asc()).all()
    created = 0
    for u in users:
        if u.id in existing_user_ids:
            continue
        db.add(
            Employee(
                user_id=u.id,
                full_name=u.name,
                department_id=u.department_id,
                position=(u.role.name if getattr(u, "role", None) else None),
                phone=None,
                salary=None,
                status="active" if bool(u.is_active) else "inactive",
                joined_at=getattr(u, "created_at", None),
            )
        )
        created += 1
    if created:
        db.commit()
    return created


@router.get("/employees")
def list_employees(db: DbSession, current: CurrentUser):
    if settings.BACKFILL_EMPLOYEES_FROM_USERS:
        _backfill_employees_from_users(db)
    rows = db.query(Employee).order_by(Employee.id.desc()).all()
    include_private = _can_view_private_employee_fields(current)
    return [_serialize(r, include_private=include_private) for r in rows]


@router.get("/employees/{eid}")
def get_employee(eid: int, db: DbSession, current: CurrentUser):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    return _serialize(e, include_private=_can_view_private_employee_fields(current))


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = Employee(**payload.model_dump())
    db.add(e); db.flush()
    log_action(db, current, "create", "Employee", e.id, new_value={"full_name": e.full_name})
    db.commit(); db.refresh(e)
    return _serialize(e, include_private=True)


@router.patch("/employees/{eid}")
def update_employee(eid: int, payload: EmployeeUpdate, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(e, k, v)
    log_action(db, current, "update", "Employee", e.id, new_value=changes)
    db.commit(); db.refresh(e)
    return _serialize(e, include_private=True)


@router.delete("/employees/{eid}", status_code=204)
def delete_employee(eid: int, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    db.delete(e)
    log_action(db, current, "delete", "Employee", eid)
    db.commit()
