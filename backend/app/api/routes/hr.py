from fastapi import APIRouter, HTTPException, Depends, Query

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.schemas import Employee, User
from app.models.audit_service import log_action
from app.models.factory_scope_service import selected_factory_code
from app.models.people.employees_service import (
    EmployeeCreateConflict,
    create_employee as create_employee_operation,
    ensure_employee_no_available as _ensure_employee_no_available,
    validate_employee_references as _validate_employee_references,
    validate_employee_salary as _validated_employee_salary,
    validate_hr_profile_json as _validate_hr_profile_json,
)
from app.libs.dto.people.employee_input import EmployeeCreateIn, normalize_employee_no
from app.libs.dto.people.employee_output import EmployeeCreateOut
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from datetime import datetime
from typing import Literal, Optional

class EmployeeUpdate(BaseModel):
    """All fields optional so the client can send partial updates."""
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: Optional[str] = None
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[Decimal] = Field(default=None, allow_inf_nan=True)
    status: Literal["active", "inactive", "on_leave", "terminated", "archived"] | None = None
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: Optional[dict] = None

    @field_validator("status")
    @classmethod
    def reject_null_status(cls, value):
        if value is None:
            raise ValueError("status must be active, inactive, on_leave, terminated, or archived")
        return value

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value):
        return normalize_employee_no(value)


router = APIRouter(tags=["hr"])


def _can_view_private_employee_fields(user: User) -> bool:
    perms = user_permissions(user)
    return bool({"*", "hr.employees", "payroll.manage"}.intersection(perms))


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
        payload["salary"] = float(r.salary) if r.salary is not None else None
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


EMPLOYEE_LIST_MAX_LIMIT = 500


@router.get("/employees")
def list_employees(
    db: DbSession,
    current: CurrentUser,
    q: str | None = Query(None, max_length=120),
    limit: int | None = Query(None, ge=1, le=EMPLOYEE_LIST_MAX_LIMIT),
    page: int | None = Query(None, ge=1),
    page_size: int | None = Query(None, ge=1, le=100),
    search: str | None = Query(None, max_length=120),
    include_archived: bool = False,
):
    """Employee list for pickers.

    `q` and `limit` are optional and additive: with neither, this returns
    exactly the full factory list it always did, so existing callers are
    unchanged. A screen that only needs a picker for one entity can now pass
    `q` instead of hydrating every employee.
    """
    if settings.BACKFILL_EMPLOYEES_FROM_USERS:
        _backfill_employees_from_users(db)
    if page is not None or page_size is not None:
        return _employee_directory_page(db, current, search=search if search is not None else q,
                                        page=page or 1, page_size=page_size or 50, include_archived=include_archived)
    factory_code = selected_factory_code(current)
    query = db.query(Employee).filter(Employee.factory_code == factory_code)
    if not include_archived:
        query = query.filter(Employee.status != "archived")
    term = str(q or "").strip()
    if term:
        pattern = f"%{term.lower()}%"
        # `Employee` has no free-text department column (only department_id),
        # so the searchable fields are the ones a picker would actually type.
        query = query.filter(or_(
            func.lower(func.coalesce(Employee.full_name, "")).like(pattern),
            func.lower(func.coalesce(Employee.employee_no, "")).like(pattern),
            func.lower(func.coalesce(Employee.position, "")).like(pattern),
        ))
    # `order_by` must be applied BEFORE `limit`; the reverse leaves the row
    # order undefined and SQLAlchemy warns about it.
    query = query.order_by(Employee.id.desc())
    if limit is not None:
        query = query.limit(limit)
    rows = query.all()
    include_private = _can_view_private_employee_fields(current)
    return [_serialize(r, include_private=include_private) for r in rows]



def _employee_directory_query(db, current, search, include_archived=False):
    query = db.query(Employee).filter(Employee.factory_code == selected_factory_code(current))
    if not include_archived:
        query = query.filter(Employee.status != "archived")
    normalized = (search or "").strip()
    if normalized:
        pattern = '%' + normalized.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Employee.full_name.ilike(pattern, escape='\\'),
                                 Employee.employee_no.ilike(pattern, escape='\\'),
                                 Employee.position.ilike(pattern, escape='\\')))
    return query


@router.get('/employees/export.xlsx')
def export_employees(
    db: DbSession,
    current: CurrentUser,
    search: str = Query("", max_length=120),
    lang: Literal["en", "ru", "uz"] = "en",
    include_archived: bool = False,
):
    from fastapi.responses import Response
    from sqlalchemy.orm import aliased
    from app.schemas import Department
    from app.schemas.people.hr import HrPosition
    from app.models.employee_export_service import employee_workbook

    factory = selected_factory_code(current)
    manager = aliased(Employee)
    rows = _employee_directory_query(db, current, search, include_archived).with_entities(
        Employee, Department.name, HrPosition.name, manager.full_name,
    ).outerjoin(Department, Department.id == Employee.department_id).outerjoin(
        HrPosition, (HrPosition.id == Employee.hr_position_id) & (HrPosition.factory_code == factory),
    ).outerjoin(manager, (manager.id == Employee.manager_employee_id) & (manager.factory_code == factory)).order_by(Employee.id.desc())
    content = employee_workbook(rows.yield_per(200), lang, include_private=_can_view_private_employee_fields(current))
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="employees-{factory}.xlsx"', "Cache-Control": "no-store"})


def _employee_directory_page(db, current, *, search, page, page_size, include_archived=False):
    from sqlalchemy import case, select, cast
    from sqlalchemy.orm import aliased, load_only
    from app.schemas.people.hr import HrPosition

    factory = selected_factory_code(current)
    private = _can_view_private_employee_fields(current)
    normalized = (search or "").strip()
    query = _employee_directory_query(db, current, normalized, include_archived)
    total, active = query.with_entities(func.count(Employee.id), func.sum(case((Employee.status == 'active', 1), else_=0))).one()
    total, active = int(total or 0), int(active or 0)
    coverage = None
    if private:
        if db.get_bind().dialect.name == 'sqlite':
            keys = func.json_each(Employee.hr_profile_json).table_valued('key')
        else:
            from sqlalchemy.dialects.postgresql import JSONB
            profile = cast(Employee.hr_profile_json, JSONB)
            safe_profile = case((func.jsonb_typeof(profile) == 'object', profile), else_=cast({}, JSONB))
            keys = func.jsonb_object_keys(safe_profile).table_valued('key')
        key_count = select(func.count()).select_from(keys).correlate(Employee).scalar_subquery()
        covered = query.filter(key_count >= 5).with_entities(func.count(Employee.id)).scalar() or 0
        coverage = round(covered * 100 / total) if total else 0
    manager = aliased(Employee)
    fields = [Employee.id, Employee.factory_code, Employee.employee_no, Employee.user_id, Employee.full_name,
              Employee.department_id, Employee.position, Employee.status, Employee.joined_at,
              Employee.manager_employee_id, Employee.hr_position_id]
    if private:
        fields += [Employee.phone, Employee.salary, Employee.hr_profile_json]
    rows = query.with_entities(Employee, manager.full_name, HrPosition.name).options(load_only(*fields)).outerjoin(
        manager, (manager.id == Employee.manager_employee_id) & (manager.factory_code == factory)
    ).outerjoin(HrPosition, (HrPosition.id == Employee.hr_position_id) & (HrPosition.factory_code == factory)).order_by(
        Employee.id.desc()
    ).offset((page-1)*page_size).limit(page_size).all()
    return {'rows': [{**_serialize(row, include_private=private), 'manager_name': manager_name,
                      'position_name': position_name} for row, manager_name, position_name in rows],
            'total': total, 'page': page, 'page_size': page_size, 'has_more': page*page_size < total, 'include_archived': include_archived,
            'active_total': active, 'inactive_total': total-active, 'profile_coverage_percent': coverage, 'search': normalized}


@router.get('/employees/manager-options')
def employee_manager_options(db: DbSession, current: CurrentUser, search: str = Query('', max_length=120),
                             selected_id: int | None = Query(None, ge=1)):
    return _directory_options(db, current, Employee, search, selected_id)


@router.get('/employees/position-options')
def employee_position_options(db: DbSession, current: CurrentUser, search: str = Query('', max_length=120),
                              selected_id: int | None = Query(None, ge=1)):
    from app.schemas.people.hr import HrPosition
    return _directory_options(db, current, HrPosition, search, selected_id)


def _directory_options(db, current, model, search, selected_id):
    factory = selected_factory_code(current)
    name = model.full_name if model is Employee else model.name
    query = db.query(model.id, name).filter(model.factory_code == factory)
    if model is Employee:
        query = query.filter(Employee.status != "archived")
    if search.strip():
        pattern = '%' + search.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        condition = name.ilike(pattern, escape='\\')
        if model is Employee:
            condition = or_(condition, model.employee_no.ilike(pattern, escape='\\'))
        query = query.filter(condition)
    rows = query.order_by(name, model.id).limit(51).all()
    key = 'full_name' if model is Employee else 'name'
    options = [{'id': row[0], key: row[1]} for row in rows[:50]]
    if selected_id and selected_id not in {row['id'] for row in options}:
        selected = db.query(model.id, name).filter(model.id == selected_id, model.factory_code == factory).first()
        if selected:
            options = options[:49] + [{'id': selected[0], key: selected[1]}]
    return {'rows': options, 'has_more': len(rows)>50}

@router.get("/employees/{eid}")
def get_employee(eid: int, db: DbSession, current: CurrentUser):
    e = db.query(Employee).filter(
        Employee.id == eid,
        Employee.factory_code == selected_factory_code(current),
    ).first()
    if not e: raise HTTPException(404, "Employee not found")
    return _serialize(e, include_private=_can_view_private_employee_fields(current))


@router.post("/employees", status_code=201, response_model=EmployeeCreateOut)
def create_employee(
    payload: EmployeeCreateIn,
    db: DbSession,
    current: User = Depends(require_permissions("hr.employees", "payroll.manage", "*")),
) -> EmployeeCreateOut:
    try:
        return create_employee_operation(current, db, payload)
    except EmployeeCreateConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/employees/{eid}")
def update_employee(eid: int, payload: EmployeeUpdate, db: DbSession, current: User = Depends(require_permissions("hr.employees", "payroll.manage", "*"))):
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
    if "salary" in changes:
        changes["salary"] = _validated_employee_salary(changes["salary"])
    if "hr_profile_json" in changes:
        changes["hr_profile_json"] = _validate_hr_profile_json(changes["hr_profile_json"], existing_profile=e.hr_profile_json)
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
    _archive_employee(eid, db, current)


@router.post("/employees/{eid}/archive", status_code=204)
def archive_employee(eid: int, db: DbSession, current: User = Depends(require_permissions("hr.employees", "payroll.manage", "*"))):
    _archive_employee(eid, db, current)


def _archive_employee(eid: int, db: DbSession, current: User):
    e = db.query(Employee).filter(
        Employee.id == eid,
        Employee.factory_code == selected_factory_code(current),
    ).with_for_update().first()
    if not e: raise HTTPException(404, "Employee not found")
    if e.status == "archived":
        return
    old_status = e.status
    e.status = "archived"
    log_action(db, current, "archive", "Employee", eid,
               old_value={"status": old_status}, new_value={"status": "archived"})
    db.commit()
