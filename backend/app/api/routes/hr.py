from fastapi import APIRouter, HTTPException, Depends

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.models import Employee, User
from app.services.audit import log_action
from app.services.factory_scope import factory_for_department, selected_factory_code
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from datetime import datetime
from typing import Optional


class EmployeeIn(BaseModel):
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: str
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
    status: str = "active"
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: dict = Field(default_factory=dict)

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value):
        return _normalize_employee_no(value)


class EmployeeUpdate(BaseModel):
    """All fields optional so the client can send partial updates."""
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
    status: Optional[str] = None
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: Optional[dict] = None

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value):
        return _normalize_employee_no(value)


router = APIRouter(tags=["hr"])


def _normalize_employee_no(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _ensure_employee_no_available(
    db: DbSession,
    factory_code: str,
    employee_no: str | None,
    *,
    exclude_id: int | None = None,
) -> None:
    if not employee_no:
        return
    qry = db.query(Employee.id).filter(
        Employee.factory_code == factory_code,
        Employee.employee_no == employee_no,
    )
    if exclude_id is not None:
        qry = qry.filter(Employee.id != exclude_id)
    if qry.first():
        raise HTTPException(409, "Employee number already exists in this factory")


def _can_view_private_employee_fields(user: User) -> bool:
    perms = user_permissions(user)
    return "*" in perms or "hr.employees" in perms


def _serialize(r: Employee, *, include_private: bool = False) -> dict:
    payload = {
        "id": r.id, "factory_code": r.factory_code, "employee_no": r.employee_no, "user_id": r.user_id, "full_name": r.full_name,
        "department_id": r.department_id, "position": r.position,
        "status": r.status, "joined_at": r.joined_at,
        "manager_employee_id": r.manager_employee_id,
        "hr_position_id": r.hr_position_id,
    }
    if include_private:
        payload["phone"] = r.phone
        payload["salary"] = float(r.salary) if r.salary else None
        payload["hr_profile_json"] = r.hr_profile_json or {}
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
                factory_code=u.factory_code,
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
    factory_code = selected_factory_code(current)
    rows = db.query(Employee).filter(Employee.factory_code == factory_code).order_by(Employee.id.desc()).all()
    include_private = _can_view_private_employee_fields(current)
    return [_serialize(r, include_private=include_private) for r in rows]


@router.get("/employees/{eid}")
def get_employee(eid: int, db: DbSession, current: CurrentUser):
    e = db.query(Employee).filter(
        Employee.id == eid,
        Employee.factory_code == selected_factory_code(current),
    ).first()
    if not e: raise HTTPException(404, "Employee not found")
    return _serialize(e, include_private=_can_view_private_employee_fields(current))


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    factory_code = selected_factory_code(current)
    _validate_employee_references(
        db, factory_code, payload.user_id, payload.department_id,
        payload.manager_employee_id, payload.hr_position_id,
    )
    values = payload.model_dump()
    _ensure_employee_no_available(db, factory_code, values.get("employee_no"))
    e = Employee(factory_code=factory_code, **values)
    db.add(e)
    try:
        db.flush()
        log_action(
            db,
            current,
            "create",
            "Employee",
            e.id,
            new_value={"employee_no": e.employee_no, "full_name": e.full_name},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Employee number already exists in this factory") from exc
    db.refresh(e)
    return _serialize(e, include_private=True)


@router.patch("/employees/{eid}")
def update_employee(eid: int, payload: EmployeeUpdate, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    factory_code = selected_factory_code(current)
    e = db.query(Employee).filter(Employee.id == eid, Employee.factory_code == factory_code).first()
    if not e: raise HTTPException(404, "Employee not found")
    changes = payload.model_dump(exclude_unset=True)
    _validate_employee_references(
        db,
        factory_code,
        changes.get("user_id", e.user_id),
        changes.get("department_id", e.department_id),
        changes.get("manager_employee_id", e.manager_employee_id),
        changes.get("hr_position_id", e.hr_position_id),
        employee_id=e.id,
    )
    if "employee_no" in changes:
        _ensure_employee_no_available(db, factory_code, changes["employee_no"], exclude_id=e.id)
    for k, v in changes.items():
        setattr(e, k, v)
    try:
        log_action(db, current, "update", "Employee", e.id, new_value=changes)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Employee number already exists in this factory") from exc
    db.refresh(e)
    return _serialize(e, include_private=True)


@router.delete("/employees/{eid}", status_code=204)
def delete_employee(eid: int, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    e = db.query(Employee).filter(
        Employee.id == eid,
        Employee.factory_code == selected_factory_code(current),
    ).first()
    if not e: raise HTTPException(404, "Employee not found")
    db.delete(e)
    log_action(db, current, "delete", "Employee", eid)
    db.commit()


def _validate_employee_references(
    db: DbSession,
    factory_code: str,
    user_id: int | None,
    department_id: int | None,
    manager_employee_id: int | None = None,
    hr_position_id: int | None = None,
    *,
    employee_id: int | None = None,
) -> None:
    if user_id is not None:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Employee user not found")
        if user.factory_code != factory_code:
            raise HTTPException(409, "Employee user belongs to another factory")
    if department_id is not None:
        from app.models import Department

        department = db.get(Department, department_id)
        if not department:
            raise HTTPException(404, "Employee department not found")
        department_factory = factory_for_department(department.code)
        if department_factory and department_factory != factory_code:
            raise HTTPException(409, "Employee department belongs to another factory")
    if manager_employee_id is not None:
        if manager_employee_id == employee_id:
            raise HTTPException(409, "Employee cannot be their own manager")
        manager = db.query(Employee).filter(
            Employee.id == manager_employee_id,
            Employee.factory_code == factory_code,
        ).first()
        if not manager:
            raise HTTPException(404, "Employee manager not found in this factory")
    if hr_position_id is not None:
        from app.models import HrPosition

        position = db.query(HrPosition).filter(
            HrPosition.id == hr_position_id,
            HrPosition.factory_code == factory_code,
        ).first()
        if not position:
            raise HTTPException(404, "HR position not found in this factory")
