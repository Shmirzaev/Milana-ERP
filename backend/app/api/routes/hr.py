from fastapi import APIRouter, HTTPException, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
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


def _serialize(r: Employee) -> dict:
    return {
        "id": r.id, "user_id": r.user_id, "full_name": r.full_name,
        "department_id": r.department_id, "position": r.position,
        "phone": r.phone, "salary": float(r.salary) if r.salary else None,
        "status": r.status, "joined_at": r.joined_at,
    }


@router.get("/employees")
def list_employees(db: DbSession, _: CurrentUser):
    rows = db.query(Employee).order_by(Employee.id.desc()).all()
    return [_serialize(r) for r in rows]


@router.get("/employees/{eid}")
def get_employee(eid: int, db: DbSession, _: CurrentUser):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    return _serialize(e)


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = Employee(**payload.model_dump())
    db.add(e); db.flush()
    log_action(db, current, "create", "Employee", e.id, new_value={"full_name": e.full_name})
    db.commit(); db.refresh(e)
    return _serialize(e)


@router.patch("/employees/{eid}")
def update_employee(eid: int, payload: EmployeeUpdate, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(e, k, v)
    log_action(db, current, "update", "Employee", e.id, new_value=changes)
    db.commit(); db.refresh(e)
    return _serialize(e)


@router.delete("/employees/{eid}", status_code=204)
def delete_employee(eid: int, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = db.get(Employee, eid)
    if not e: raise HTTPException(404, "Employee not found")
    db.delete(e)
    log_action(db, current, "delete", "Employee", eid)
    db.commit()
