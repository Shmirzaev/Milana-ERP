"""Employee creation and shared HR validation used by the existing update route."""

import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.libs.dto.people.employee_profile import EmployeeProfileJson
from app.models.audit_service import log_action
from app.models.factory_scope_service import factory_for_department, selected_factory_code
from app.schemas import Employee, User
from app.schemas.people.employee_persistence import insert_employee, update_employee_fields

MAX_EMPLOYEE_SALARY = Decimal("9999999999.99")
EMPLOYEE_SALARY_STEP = Decimal("0.0001")
_MAX_HR_PROFILE_JSON_BYTES = 16 * 1024
_MAX_HR_PROFILE_JSON_DEPTH = 16


def create_employee(db: Session, current: User, values: dict) -> Employee:
    factory_code = selected_factory_code(current)
    _validate_employee_references(
        db, factory_code, values.get("user_id"), values.get("department_id"),
        values.get("manager_employee_id"), values.get("hr_position_id"),
    )
    values = values.copy()
    _ensure_employee_no_available(db, factory_code, values.get("employee_no"))
    values["salary"] = _validated_employee_salary(values["salary"])
    values["hr_profile_json"] = _validate_hr_profile_json(values["hr_profile_json"])
    employee = insert_employee(db, factory_code=factory_code, values=values)
    try:
        db.flush()
        log_action(
            db, current, "create", "Employee", employee.id,
            new_value={"employee_no": employee.employee_no, "full_name": employee.full_name},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Employee number already exists in this factory") from exc
    db.refresh(employee)
    return employee


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
    db: Session,
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
    from app.models.employee_aliases_service import merged_employee
    alias = merged_employee(db, factory_code, employee_no=employee_no)
    if alias and alias.id != exclude_id:
        raise HTTPException(409, "Employee number is retained for a merged employee in this factory")


def _validate_employee_references(
    db: Session,
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
        from app.schemas import Department

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
        from app.schemas import HrPosition

        position = db.query(HrPosition).filter(
            HrPosition.id == hr_position_id,
            HrPosition.factory_code == factory_code,
        ).first()
        if not position:
            raise HTTPException(404, "HR position not found in this factory")


def update_employee(db: Session, current: User, eid: int, changes: dict, *, audit: Callable) -> Employee:
    factory_code = selected_factory_code(current)
    e = db.query(Employee).filter(Employee.id == eid, Employee.factory_code == factory_code).first()
    if not e: raise HTTPException(404, "Employee not found")
    changes = changes.copy()
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
    update_employee_fields(db, employee=e, changes=changes)
    try:
        audit(db, current, "update", "Employee", e.id, new_value=changes)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Employee number already exists in this factory") from exc
    db.refresh(e)
    return e


def archive_employee(db: Session, current: User, eid: int, *, audit: Callable) -> None:
    e = db.query(Employee).filter(
        Employee.id == eid,
        Employee.factory_code == selected_factory_code(current),
    ).with_for_update().first()
    if not e: raise HTTPException(404, "Employee not found")
    if e.status == "archived":
        return
    old_status = e.status
    update_employee_fields(db, employee=e, changes={"status": "archived"})
    audit(db, current, "archive", "Employee", eid,
               old_value={"status": old_status}, new_value={"status": "archived"})
    db.commit()
