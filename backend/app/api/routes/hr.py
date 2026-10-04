import json
from math import isfinite

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.models import Employee, User
from app.services.audit import log_action
from app.services.factory_scope import factory_for_department, selected_factory_code
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime
from typing import Literal, Optional


MAX_EMPLOYEE_SALARY = Decimal("9999999999.99")
EMPLOYEE_SALARY_STEP = Decimal("0.0001")


class EmployeeIn(BaseModel):
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: str
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[Decimal] = Field(default=None, allow_inf_nan=True)
    status: Literal["active", "inactive", "on_leave", "terminated"] = "active"
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
    salary: Optional[Decimal] = Field(default=None, allow_inf_nan=True)
    status: Literal["active", "inactive", "on_leave", "terminated"] | None = None
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: Optional[dict] = None

    @field_validator("status")
    @classmethod
    def reject_null_status(cls, value):
        if value is None:
            raise ValueError("status must be active, inactive, on_leave, or terminated")
        return value

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value):
        return _normalize_employee_no(value)


_MAX_HR_PROFILE_JSON_BYTES = 16 * 1024
_MAX_HR_PROFILE_JSON_DEPTH = 16


class EmployeeProfileJson(BaseModel):
    """Persisted fields supported by the employee profile editor and reports."""

    model_config = ConfigDict(extra="forbid", strict=True)

    photo_url: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    email: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    nationality: str | None = None
    company: str | None = None
    branch: str | None = None
    section: str | None = None
    grade_level: str | None = None
    employment_type: str | None = None
    probation_end: str | None = None
    work_schedule: str | None = None
    shift: str | None = None
    workplace: str | None = None
    scheduled_daily_hours: str | int | float | None = None
    rate_type: str | None = None
    bonus_scheme: str | None = None
    bank_details: str | None = None
    payroll_id: str | None = None


router = APIRouter(tags=["hr"])


def _normalize_employee_no(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _validated_employee_salary(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite():
        raise HTTPException(422, "Employee salary must be a finite number")
    if value < 0:
        raise HTTPException(422, "Employee salary must be nonnegative")
    if value > MAX_EMPLOYEE_SALARY:
        raise HTTPException(422, f"Employee salary must be no more than {MAX_EMPLOYEE_SALARY}")
    try:
        return value.quantize(EMPLOYEE_SALARY_STEP, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise HTTPException(422, "Employee salary must be a finite number") from exc


def _same_json_value(left: object, right: object) -> bool:
    pending = [(left, right)]
    while pending:
        current_left, current_right = pending.pop()
        if type(current_left) is not type(current_right):
            return False
        if isinstance(current_left, dict):
            if current_left.keys() != current_right.keys():
                return False
            pending.extend((current_left[key], current_right[key]) for key in current_left)
        elif isinstance(current_left, list):
            if len(current_left) != len(current_right):
                return False
            pending.extend(zip(current_left, current_right))
        elif current_left != current_right:
            return False
    return True


def _validate_hr_profile_json_bounds(value: dict, existing_profile: object) -> None:
    pending = [(value, 1)]
    exceeds_depth = False
    while pending:
        current, depth = pending.pop()
        if isinstance(current, dict):
            if depth > _MAX_HR_PROFILE_JSON_DEPTH:
                exceeds_depth = True
            pending.extend((nested, depth + 1) for nested in current.values())
        elif isinstance(current, list):
            if depth > _MAX_HR_PROFILE_JSON_DEPTH:
                exceeds_depth = True
            pending.extend((nested, depth + 1) for nested in current)

    if _same_json_value(value, existing_profile):
        return
    if exceeds_depth:
        raise HTTPException(422, "hr_profile_json exceeds the maximum nesting depth")

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise HTTPException(422, "hr_profile_json must contain valid JSON values") from exc
    if len(encoded) > _MAX_HR_PROFILE_JSON_BYTES:
        raise HTTPException(422, "hr_profile_json exceeds the 16 KiB limit")


def _validate_hr_profile_json(
    value: dict,
    *,
    existing_profile: object = None,
) -> dict:
    if not isinstance(value, dict):
        raise HTTPException(422, "hr_profile_json must be a JSON object")
    _validate_hr_profile_json_bounds(value, existing_profile)
    if _same_json_value(value, existing_profile):
        return value
    existing = existing_profile if isinstance(existing_profile, dict) else {}
    known_fields = EmployeeProfileJson.model_fields.keys()
    unknown_keys = set(value) - known_fields
    unchanged_unknown = bool(unknown_keys) and all(
        key in existing and _same_json_value(value[key], existing[key])
        for key in unknown_keys
    )
    schema_value = (
        {key: item for key, item in value.items() if key in known_fields}
        if unchanged_unknown
        else value
    )
    try:
        EmployeeProfileJson.model_validate(schema_value)
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", "hr_profile_json", *error["loc"])}
            for error in exc.errors()
        ]) from exc
    if "scheduled_daily_hours" in value:
        raw_hours = value["scheduled_daily_hours"]
        valid_hours = raw_hours is None or (type(raw_hours) is str and raw_hours == "")
        if not valid_hours:
            if type(raw_hours) not in (str, int, float):
                hours = float("nan")
            else:
                try:
                    hours = float(raw_hours)
                except (OverflowError, TypeError, ValueError):
                    hours = float("nan")
            valid_hours = isfinite(hours) and 0 < hours <= 24
        if not valid_hours:
            old_hours = existing.get("scheduled_daily_hours")
            if not (
                "scheduled_daily_hours" in existing
                and _same_json_value(raw_hours, old_hours)
            ):
                raise HTTPException(
                    422,
                    "scheduled_daily_hours must be finite and greater than 0 and no more than 24",
                )
    # Validation is intentionally write-only. Keep the caller's scalar types
    # and sparse keys unchanged so existing API responses remain compatible.
    return value


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
                                        page=page or 1, page_size=page_size or 50)
    factory_code = selected_factory_code(current)
    query = db.query(Employee).filter(Employee.factory_code == factory_code)
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



def _employee_directory_page(db, current, *, search, page, page_size):
    from sqlalchemy import case, select, cast
    from sqlalchemy.orm import aliased, load_only
    from app.models.hr import HrPosition

    factory = selected_factory_code(current)
    private = _can_view_private_employee_fields(current)
    normalized = (search or "").strip()
    query = db.query(Employee).filter(Employee.factory_code == factory)
    if normalized:
        pattern = '%' + normalized.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Employee.full_name.ilike(pattern, escape='\\'),
                                 Employee.employee_no.ilike(pattern, escape='\\'),
                                 Employee.position.ilike(pattern, escape='\\')))
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
            'total': total, 'page': page, 'page_size': page_size, 'has_more': page*page_size < total,
            'active_total': active, 'inactive_total': total-active, 'profile_coverage_percent': coverage, 'search': normalized}


@router.get('/employees/manager-options')
def employee_manager_options(db: DbSession, current: CurrentUser, search: str = Query('', max_length=120),
                             selected_id: int | None = Query(None, ge=1)):
    return _directory_options(db, current, Employee, search, selected_id)


@router.get('/employees/position-options')
def employee_position_options(db: DbSession, current: CurrentUser, search: str = Query('', max_length=120),
                              selected_id: int | None = Query(None, ge=1)):
    from app.models.hr import HrPosition
    return _directory_options(db, current, HrPosition, search, selected_id)


def _directory_options(db, current, model, search, selected_id):
    factory = selected_factory_code(current)
    name = model.full_name if model is Employee else model.name
    query = db.query(model.id, name).filter(model.factory_code == factory)
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


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    factory_code = selected_factory_code(current)
    _validate_employee_references(
        db, factory_code, payload.user_id, payload.department_id,
        payload.manager_employee_id, payload.hr_position_id,
    )
    values = payload.model_dump()
    _ensure_employee_no_available(db, factory_code, values.get("employee_no"))
    values["salary"] = _validated_employee_salary(values["salary"])
    values["hr_profile_json"] = _validate_hr_profile_json(values["hr_profile_json"])
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
