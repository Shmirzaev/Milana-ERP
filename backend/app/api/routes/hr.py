from typing import Annotated
from decimal import Decimal, InvalidOperation
from math import isfinite

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.deps import DbSession, CurrentUser, require_permissions, user_permissions
from app.models import Employee, Role, User
from app.schemas.hr import EmployeeOut, EmployeePageOut
from app.services.audit import log_action
from app.services.factory_scope import factory_for_department, selected_factory_code
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, or_, cast, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, load_only, noload
from datetime import datetime
from typing import Literal, Optional


MAX_EMPLOYEE_SALARY = Decimal("9999999999.99")
_EMPLOYEE_TEXT_LIMITS = {"full_name": 255, "position": 128, "phone": 64}


class EmployeeIn(BaseModel):
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: str
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
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
    salary: Optional[float] = None
    status: Literal["active", "inactive", "on_leave", "terminated"] | None = None
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: Optional[dict] = None

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value):
        return _normalize_employee_no(value)


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


def _same_json_value(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            left.keys() == right.keys()
            and all(_same_json_value(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    return left == right


def _validate_hr_profile_json(
    value: dict,
    *,
    existing_profile: object = None,
) -> dict:
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


def _validated_employee_salary(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        salary = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "Employee salary must be a finite number") from None
    if not salary.is_finite():
        raise HTTPException(422, "Employee salary must be a finite number")
    if salary < 0:
        raise HTTPException(422, "Employee salary must be nonnegative")
    if salary > MAX_EMPLOYEE_SALARY:
        raise HTTPException(422, f"Employee salary must be no more than {MAX_EMPLOYEE_SALARY}")
    return salary


def _validate_employee_text_storage(values: dict) -> None:
    for field, maximum in _EMPLOYEE_TEXT_LIMITS.items():
        value = values.get(field)
        if value is not None and len(value) > maximum:
            raise HTTPException(422, f"{field} must be at most {maximum} characters")


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
    users = (
        db.query(User)
        .options(
            load_only(
                User.id,
                User.name,
                User.factory_code,
                User.department_id,
                User.is_active,
                User.created_at,
            ),
            joinedload(User.role).load_only(Role.id, Role.name),
            noload(User.department),
        )
        .order_by(User.id.asc())
        .all()
    )
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


@router.get(
    "/employees",
    response_model=list[EmployeeOut] | EmployeePageOut,
    response_model_exclude_unset=True,
)
def list_employees(
    db: DbSession,
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
    search: Annotated[str | None, Query(max_length=120)] = None,
):
    if settings.BACKFILL_EMPLOYEES_FROM_USERS:
        _backfill_employees_from_users(db)
    factory_code = selected_factory_code(current)
    include_private = _can_view_private_employee_fields(current)
    employee_fields = [
        Employee.id,
        Employee.factory_code,
        Employee.employee_no,
        Employee.user_id,
        Employee.full_name,
        Employee.department_id,
        Employee.position,
        Employee.status,
        Employee.joined_at,
        Employee.manager_employee_id,
        Employee.hr_position_id,
    ]
    if include_private:
        employee_fields.extend([Employee.phone, Employee.salary, Employee.hr_profile_json])
    query = db.query(Employee).options(load_only(*employee_fields)).filter(Employee.factory_code == factory_code)
    normalized_search = (search or "").strip()
    if normalized_search:
        escaped = normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(
            Employee.full_name.ilike(pattern, escape="\\"),
            Employee.employee_no.ilike(pattern, escape="\\"),
            Employee.position.ilike(pattern, escape="\\"),
        ))
    ordered_query = query.order_by(Employee.id.desc())
    paginated = page is not None or page_size is not None
    effective_page = page or 1
    effective_page_size = page_size or limit
    total = int(query.with_entities(func.count(Employee.id)).scalar() or 0) if paginated else None
    if paginated:
        summary = query.with_entities(
            func.sum(case((Employee.status == "active", 1), else_=0)),
            func.sum(case((Employee.status != "active", 1), else_=0)),
        ).first()
        active_total = int(summary[0] or 0)
        inactive_total = int(summary[1] or 0)
        profile_coverage_percent = None
        if include_private:
            if db.bind.dialect.name == "sqlite":
                profile_keys = (
                    db.query(func.count())
                    .select_from(func.json_each(Employee.hr_profile_json).table_valued("key"))
                    .correlate(Employee)
                    .scalar_subquery()
                )
            else:
                from sqlalchemy.dialects.postgresql import JSONB

                profile_json = cast(Employee.hr_profile_json, JSONB)
                profile_type = func.jsonb_typeof(profile_json)
                profile_keys = case(
                    (profile_type == "object", func.jsonb_object_length(profile_json)),
                    (profile_type == "array", func.jsonb_array_length(profile_json)),
                    else_=0,
                )
            covered = int(query.filter(profile_keys >= 5).with_entities(func.count(Employee.id)).scalar() or 0)
            profile_coverage_percent = round(covered * 100 / total) if total else 0
    if paginated:
        from sqlalchemy.orm import aliased

        manager = aliased(Employee)
        rows = (
            db.query(Employee, manager.full_name)
            .options(load_only(*employee_fields))
            .outerjoin(manager, (manager.id == Employee.manager_employee_id) & (manager.factory_code == factory_code))
            .filter(Employee.factory_code == factory_code)
        )
        if normalized_search:
            rows = rows.filter(or_(
                Employee.full_name.ilike(pattern, escape="\\"),
                Employee.employee_no.ilike(pattern, escape="\\"),
                Employee.position.ilike(pattern, escape="\\"),
            ))
        rows = rows.order_by(Employee.id.desc()).offset((effective_page - 1) * effective_page_size).limit(effective_page_size).all()
    else:
        rows = ordered_query.limit(limit).all()
    if paginated:
        serialized = [
            {**_serialize(row, include_private=include_private), **({"manager_name": manager_name} if manager_name else {})}
            for row, manager_name in rows
        ]
    else:
        serialized = [_serialize(r, include_private=include_private) for r in rows]
    if not paginated:
        return serialized
    return {
        "rows": serialized,
        "total": total or 0,
        "page": effective_page,
        "page_size": effective_page_size,
        "has_more": effective_page * effective_page_size < (total or 0),
        "active_total": active_total,
        "inactive_total": inactive_total,
        "profile_coverage_percent": profile_coverage_percent,
        "search": normalized_search,
    }


@router.get("/employees/manager-options")
def employee_manager_options(
    db: DbSession,
    current: CurrentUser,
    search: Annotated[str, Query(max_length=120)] = "",
    selected_id: Annotated[int | None, Query(ge=1)] = None,
):
    factory_code = selected_factory_code(current)
    query = db.query(Employee.id, Employee.full_name).filter(Employee.factory_code == factory_code)
    normalized_search = search.strip()
    if normalized_search:
        escaped = normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(or_(Employee.full_name.ilike(pattern, escape="\\"), Employee.employee_no.ilike(pattern, escape="\\")))
    rows = query.order_by(Employee.full_name.asc(), Employee.id.asc()).limit(51).all()
    has_more = len(rows) > 50
    options = [{"id": int(row.id), "full_name": row.full_name} for row in rows[:50]]
    if selected_id and all(row["id"] != selected_id for row in options):
        selected = db.query(Employee.id, Employee.full_name).filter(
            Employee.factory_code == factory_code, Employee.id == selected_id,
        ).first()
        if selected:
            if len(options) == 50:
                options.pop()
            options.append({"id": int(selected.id), "full_name": selected.full_name})
    return {"rows": options, "has_more": has_more}


@router.get("/employees/{eid}")
def get_employee(eid: int, db: DbSession, current: CurrentUser):
    include_private = _can_view_private_employee_fields(current)
    employee_fields = [
        Employee.id,
        Employee.factory_code,
        Employee.employee_no,
        Employee.user_id,
        Employee.full_name,
        Employee.department_id,
        Employee.position,
        Employee.status,
        Employee.joined_at,
        Employee.manager_employee_id,
        Employee.hr_position_id,
    ]
    if include_private:
        employee_fields.extend([Employee.phone, Employee.salary, Employee.hr_profile_json])
    e = (
        db.query(Employee)
        .options(load_only(*employee_fields))
        .filter(
            Employee.id == eid,
            Employee.factory_code == selected_factory_code(current),
        )
        .first()
    )
    if not e: raise HTTPException(404, "Employee not found")
    return _serialize(e, include_private=include_private)


@router.post("/employees", status_code=201)
def create_employee(payload: EmployeeIn, db: DbSession, current: User = Depends(require_permissions("hr.employees", "*"))):
    factory_code = selected_factory_code(current)
    _validate_employee_references(
        db, factory_code, payload.user_id, payload.department_id,
        payload.manager_employee_id, payload.hr_position_id,
    )
    values = payload.model_dump()
    _ensure_employee_no_available(db, factory_code, values.get("employee_no"))
    values["hr_profile_json"] = _validate_hr_profile_json(values["hr_profile_json"])
    values["salary"] = _validated_employee_salary(values["salary"])
    _validate_employee_text_storage(values)
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
        allow_inactive_department_id=e.department_id,
    )
    if "employee_no" in changes:
        _ensure_employee_no_available(db, factory_code, changes["employee_no"], exclude_id=e.id)
    if "hr_profile_json" in changes:
        changes["hr_profile_json"] = _validate_hr_profile_json(
            changes["hr_profile_json"],
            existing_profile=e.hr_profile_json,
        )
    if "salary" in changes:
        changes["salary"] = _validated_employee_salary(changes["salary"])
    _validate_employee_text_storage(changes)
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
    allow_inactive_department_id: int | None = None,
) -> None:
    if user_id is not None:
        if not -2_147_483_648 <= user_id <= 2_147_483_647:
            raise HTTPException(404, "Employee user not found")
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
        if not department.is_active and department_id != allow_inactive_department_id:
            raise HTTPException(422, "Inactive departments cannot be newly assigned")
        department_factory = factory_for_department(department.code)
        if department_factory and department_factory != factory_code:
            raise HTTPException(409, "Employee department belongs to another factory")
    if manager_employee_id is not None:
        if manager_employee_id == employee_id:
            raise HTTPException(409, "Employee cannot be their own manager")
        manager = db.query(Employee.id).filter(
            Employee.id == manager_employee_id,
            Employee.factory_code == factory_code,
        ).first()
        if not manager:
            raise HTTPException(404, "Employee manager not found in this factory")
    if hr_position_id is not None:
        from app.models import HrPosition

        position = db.query(HrPosition.id).filter(
            HrPosition.id == hr_position_id,
            HrPosition.factory_code == factory_code,
        ).first()
        if not position:
            raise HTTPException(404, "HR position not found in this factory")
