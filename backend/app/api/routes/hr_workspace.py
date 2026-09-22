from __future__ import annotations

import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.models import (
    AttendanceEvent,
    Department,
    Employee,
    HrCalendarEvent,
    HrEmployeeDocument,
    HrOrgUnit,
    HrPosition,
    HrRecruitmentCandidate,
    SystemSetting,
    User,
)
from app.services.audit import log_action
from app.services.attendance_event_policy import accepted_attendance_result
from app.services.attendance_reports import TASHKENT
from app.services.factory_scope import factory_for_department, selected_factory_code


router = APIRouter(prefix="/hr", tags=["hr-workspace"])
HrUser = Depends(require_permissions("hr.employees", "*"))
MAX_INT4 = 2_147_483_647
MAX_POSITION_SALARY = 999_999_999_999.99


class OrgUnitIn(BaseModel):
    parent_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    manager_employee_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    unit_type: str = Field(pattern="^(company|factory|department|section|team)$")
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=48)
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "Organization unit name")


class PositionIn(BaseModel):
    org_unit_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    name: str = Field(min_length=1, max_length=160)
    job_description: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    qualification_level: str | None = None
    grade_level: str | None = None
    salary_min: float | None = Field(default=None, ge=0, le=MAX_POSITION_SALARY, allow_inf_nan=False)
    salary_max: float | None = Field(default=None, ge=0, le=MAX_POSITION_SALARY, allow_inf_nan=False)
    approved_count: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("salary_min", "salary_max", mode="before")
    @classmethod
    def validate_finite_salary(cls, value):
        if isinstance(value, float) and not isfinite(value):
            raise HTTPException(422, "Salary must be a finite number")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "Position name")

    @model_validator(mode="after")
    def validate_salary_range(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class CandidateIn(BaseModel):
    position_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    full_name: str = Field(min_length=1, max_length=255)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, pattern="^(male|female|other)$")
    nationality: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    passport_number: str | None = Field(default=None, max_length=32)
    passport_issued_by: str | None = Field(default=None, max_length=255)
    passport_issue_date: date | None = None
    passport_expiry_date: date | None = None
    pinfl: str | None = Field(default=None, pattern="^[0-9]{14}$")
    phone: str | None = None
    email: str | None = None
    source: str | None = None
    stage: str = Field(default="applied", pattern="^(applied|screening|interview|offer|hired|rejected)$")
    applied_on: date | None = None
    interview_at: datetime | None = None
    notes: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return _required_text(value, "Candidate name")

    @model_validator(mode="after")
    def validate_passport_dates(self):
        if (
            self.passport_issue_date is not None
            and self.passport_expiry_date is not None
            and self.passport_expiry_date < self.passport_issue_date
        ):
            raise ValueError("Passport expiry date cannot precede its issue date")
        return self


class CalendarEventIn(BaseModel):
    employee_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    event_type: str = Field(pattern="^(birthday|contract_expiry|probation_end|leave|training|interview|medical_check|certification|performance_review|other)$")
    title: str = Field(min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime | None = None
    notes: str | None = None
    status: str = Field(default="scheduled", pattern="^(scheduled|completed|cancelled)$")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _required_text(value, "Calendar event title")

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.ends_at is None:
            return self
        starts_aware = self.starts_at.tzinfo is not None and self.starts_at.utcoffset() is not None
        ends_aware = self.ends_at.tzinfo is not None and self.ends_at.utcoffset() is not None
        if starts_aware != ends_aware:
            raise ValueError("Calendar start and end must use matching timezone formats")
        if self.ends_at < self.starts_at:
            raise ValueError("Calendar end cannot precede its start")
        return self


class HrSettingsIn(BaseModel):
    company_name: str = "Milana Premium"
    default_workday_hours: float = Field(default=8, gt=0, le=24, allow_inf_nan=False)
    default_monthly_hours: float = Field(default=176, ge=0, le=744, allow_inf_nan=False)
    probation_days: int = Field(default=90, ge=0, le=730)
    contract_warning_days: int = Field(default=30, ge=0, le=365)
    weekend_days: list[int] = Field(default_factory=lambda: [6, 7])

    @field_validator("default_workday_hours", "default_monthly_hours", mode="before")
    @classmethod
    def validate_finite_hours(cls, value):
        if isinstance(value, float) and not isfinite(value):
            raise HTTPException(422, "Scheduled hours must be finite")
        return value


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _factory(current: User) -> str:
    return selected_factory_code(current)


def _attendance_day_bounds(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=TASHKENT)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _safe_hr_settings(value) -> HrSettingsIn:
    if not isinstance(value, dict):
        return HrSettingsIn()
    try:
        return HrSettingsIn.model_validate(value)
    except (HTTPException, ValidationError):
        return HrSettingsIn()


def _load_hr_settings(db: DbSession, factory: str) -> HrSettingsIn:
    row = db.query(SystemSetting).filter(SystemSetting.key == _settings_key(factory)).first()
    return _safe_hr_settings(row.value_json if row else {})


def _scheduled_minutes(profile, default_hours: float) -> int:
    raw_hours = profile.get("scheduled_daily_hours") if isinstance(profile, dict) else None
    if raw_hours in (None, "") or isinstance(raw_hours, bool):
        hours = default_hours
    else:
        try:
            hours = float(raw_hours)
        except (OverflowError, TypeError, ValueError):
            hours = default_hours
    if not isfinite(hours) or hours <= 0 or hours > 24:
        hours = default_hours
    return int(hours * 60)


def _employee(db: DbSession, factory: str, employee_id: int) -> Employee:
    row = db.query(Employee).filter(Employee.id == employee_id, Employee.factory_code == factory).first()
    if not row:
        raise HTTPException(404, "Employee not found")
    return row


def _department(db: DbSession, factory: str, department_id: int) -> Department:
    row = db.get(Department, department_id)
    if not row:
        raise HTTPException(404, "Department not found")
    department_factory = factory_for_department(row.code)
    if department_factory and department_factory != factory:
        raise HTTPException(409, "Department belongs to another factory")
    return row


def _org_unit(db: DbSession, factory: str, unit_id: int) -> HrOrgUnit:
    row = db.query(HrOrgUnit).filter(HrOrgUnit.id == unit_id, HrOrgUnit.factory_code == factory).first()
    if not row:
        raise HTTPException(404, "Organization unit not found")
    return row


def _validate_org_unit_links(payload: OrgUnitIn, db: DbSession, factory: str) -> None:
    if payload.parent_id is not None:
        _org_unit(db, factory, payload.parent_id)
    if payload.department_id is not None:
        _department(db, factory, payload.department_id)
    if payload.manager_employee_id is not None:
        _employee(db, factory, payload.manager_employee_id)


def _validate_position_links(payload: PositionIn, db: DbSession, factory: str) -> None:
    if payload.org_unit_id is not None:
        _org_unit(db, factory, payload.org_unit_id)
    if payload.department_id is not None:
        _department(db, factory, payload.department_id)


def _position_dict(row: HrPosition, occupied: int = 0, department_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "org_unit_id": row.org_unit_id,
        "department_id": row.department_id,
        "department_name": department_name,
        "name": row.name,
        "job_description": row.job_description,
        "required_skills": row.required_skills_json or [],
        "qualification_level": row.qualification_level,
        "grade_level": row.grade_level,
        "salary_min": float(row.salary_min) if row.salary_min is not None else None,
        "salary_max": float(row.salary_max) if row.salary_max is not None else None,
        "approved_count": row.approved_count,
        "occupied_count": occupied,
        "vacant_count": max(0, row.approved_count - occupied),
        "is_active": row.is_active,
    }


@router.get("/dashboard")
def dashboard(db: DbSession, current: User = HrUser):
    factory = _factory(current)
    employees = db.query(Employee).filter(Employee.factory_code == factory).all()
    active = [row for row in employees if row.status == "active"]
    positions = db.query(HrPosition).filter(HrPosition.factory_code == factory, HrPosition.is_active.is_(True)).all()
    approved = sum(row.approved_count for row in positions)
    candidates = db.query(HrRecruitmentCandidate).filter(HrRecruitmentCandidate.factory_code == factory).count()
    upcoming = db.query(HrCalendarEvent).filter(
        HrCalendarEvent.factory_code == factory,
        HrCalendarEvent.starts_at >= datetime.now(timezone.utc),
    ).count()
    by_department: dict[str, int] = {}
    department_names = {row.id: row.name for row in db.query(Department).all()}
    for employee in active:
        name = department_names.get(employee.department_id, "Unassigned")
        by_department[name] = by_department.get(name, 0) + 1
    return {
        "headcount": len(active),
        "inactive": len(employees) - len(active),
        "approved_positions": approved,
        "vacancies": max(0, approved - len(active)),
        "candidates": candidates,
        "upcoming_events": upcoming,
        "by_department": [{"name": name, "count": count} for name, count in sorted(by_department.items())],
    }


@router.get("/organization")
def list_organization(db: DbSession, current: User = HrUser):
    factory = _factory(current)
    units = db.query(HrOrgUnit).filter(HrOrgUnit.factory_code == factory).order_by(HrOrgUnit.sort_order, HrOrgUnit.name).all()
    employees = db.query(Employee).filter(Employee.factory_code == factory).all()
    return {
        "units": [{
            "id": row.id, "parent_id": row.parent_id, "department_id": row.department_id,
            "manager_employee_id": row.manager_employee_id, "unit_type": row.unit_type,
            "name": row.name, "code": row.code, "sort_order": row.sort_order,
        } for row in units],
        "employees": [{
            "id": row.id, "employee_no": row.employee_no, "full_name": row.full_name,
            "department_id": row.department_id, "manager_employee_id": row.manager_employee_id,
            "hr_position_id": row.hr_position_id, "position": row.position, "status": row.status,
        } for row in employees],
    }


@router.post("/organization", status_code=201)
def create_org_unit(payload: OrgUnitIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    _validate_org_unit_links(payload, db, factory)
    row = HrOrgUnit(factory_code=factory, **payload.model_dump())
    db.add(row); db.flush()
    log_action(db, current, "create", "HrOrgUnit", row.id, new_value={"name": row.name, "unit_type": row.unit_type})
    db.commit(); db.refresh(row)
    return {"id": row.id}


@router.delete("/organization/{unit_id}", status_code=204)
def delete_org_unit(unit_id: int, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    row = db.query(HrOrgUnit).filter(HrOrgUnit.id == unit_id, HrOrgUnit.factory_code == factory).first()
    if not row: raise HTTPException(404, "Organization unit not found")
    db.delete(row); log_action(db, current, "delete", "HrOrgUnit", unit_id); db.commit()


@router.get("/positions")
def list_positions(db: DbSession, current: User = HrUser):
    factory = _factory(current)
    occupied = dict(db.query(Employee.hr_position_id, func.count(Employee.id)).filter(
        Employee.factory_code == factory, Employee.status == "active", Employee.hr_position_id.isnot(None),
    ).group_by(Employee.hr_position_id).all())
    rows = db.query(HrPosition).filter(HrPosition.factory_code == factory).order_by(HrPosition.name).all()
    department_ids = {int(row.department_id) for row in rows if row.department_id is not None}
    department_names = {
        int(department.id): department.name
        for department in db.query(Department).filter(Department.id.in_(department_ids)).all()
    } if department_ids else {}
    return [
        _position_dict(row, occupied.get(row.id, 0), department_names.get(int(row.department_id)) if row.department_id else None)
        for row in rows
    ]


@router.post("/positions", status_code=201)
def create_position(payload: PositionIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    _validate_position_links(payload, db, factory)
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    row = HrPosition(factory_code=factory, **values)
    db.add(row); db.flush(); log_action(db, current, "create", "HrPosition", row.id, new_value={"name": row.name}); db.commit(); db.refresh(row)
    return _position_dict(row)


@router.patch("/positions/{position_id}")
def update_position(position_id: int, payload: PositionIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    row = db.query(HrPosition).filter(HrPosition.id == position_id, HrPosition.factory_code == factory).first()
    if not row: raise HTTPException(404, "Position not found")
    _validate_position_links(payload, db, factory)
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    for key, value in values.items(): setattr(row, key, value)
    log_action(db, current, "update", "HrPosition", row.id, new_value=values); db.commit(); db.refresh(row)
    return _position_dict(row)


@router.get("/recruitment")
def list_candidates(
    db: DbSession,
    current: User = HrUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
):
    rows = db.query(HrRecruitmentCandidate).filter(
        HrRecruitmentCandidate.factory_code == _factory(current),
    ).order_by(HrRecruitmentCandidate.id.desc()).limit(limit).all()
    fields = (
        "id", "position_id", "department_id", "full_name", "first_name", "last_name", "middle_name",
        "date_of_birth", "gender", "nationality", "country", "region", "district", "address",
        "passport_number", "passport_issued_by", "passport_issue_date", "passport_expiry_date", "pinfl",
        "phone", "email", "source", "stage", "applied_on", "interview_at", "notes",
    )
    return [{key: getattr(row, key) for key in fields} for row in rows]


def _validate_candidate_links(payload: CandidateIn, db: DbSession, factory: str, candidate_id: int | None = None) -> None:
    if payload.position_id is not None and not db.query(HrPosition).filter(
        HrPosition.id == payload.position_id, HrPosition.factory_code == factory,
    ).first():
        raise HTTPException(404, "Staffing position not found")
    if payload.department_id is not None:
        _department(db, factory, payload.department_id)
    if payload.pinfl:
        duplicate = db.query(HrRecruitmentCandidate).filter(
            HrRecruitmentCandidate.factory_code == factory,
            HrRecruitmentCandidate.pinfl == payload.pinfl,
        )
        if candidate_id is not None:
            duplicate = duplicate.filter(HrRecruitmentCandidate.id != candidate_id)
        if duplicate.first():
            raise HTTPException(409, "A candidate with this PINFL already exists")


@router.post("/recruitment", status_code=201)
def create_candidate(payload: CandidateIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    _validate_candidate_links(payload, db, factory)
    row = HrRecruitmentCandidate(factory_code=factory, **payload.model_dump())
    db.add(row); db.flush(); log_action(db, current, "create", "HrRecruitmentCandidate", row.id, new_value={"full_name": row.full_name}); db.commit(); db.refresh(row)
    return {"id": row.id}


@router.patch("/recruitment/{candidate_id}")
def update_candidate(candidate_id: int, payload: CandidateIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    row = db.query(HrRecruitmentCandidate).filter(HrRecruitmentCandidate.id == candidate_id, HrRecruitmentCandidate.factory_code == factory).first()
    if not row: raise HTTPException(404, "Candidate not found")
    _validate_candidate_links(payload, db, factory, candidate_id)
    for key, value in payload.model_dump().items(): setattr(row, key, value)
    log_action(db, current, "update", "HrRecruitmentCandidate", row.id, new_value={"stage": row.stage}); db.commit()
    return {"id": row.id}


def _document_dict(row: HrEmployeeDocument, employee_name: str | None = None) -> dict:
    return {
        "id": row.id, "employee_id": row.employee_id, "employee_name": employee_name,
        "category": row.category, "title": row.title, "original_name": row.original_name,
        "content_type": row.content_type, "size_bytes": row.size_bytes,
        "expires_on": row.expires_on, "created_at": row.created_at,
        "download_url": f"/api/hr/documents/{row.id}/download",
    }


@router.get("/documents")
def list_documents(
    db: DbSession,
    current: User = HrUser,
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
):
    factory = _factory(current)
    query = db.query(HrEmployeeDocument).filter(HrEmployeeDocument.factory_code == factory)
    paginated = page is not None or page_size is not None
    safe_page = page or 1
    safe_page_size = page_size or 100
    total = query.count() if paginated else None
    if paginated:
        rows = query.order_by(HrEmployeeDocument.id.desc()).offset((safe_page - 1) * safe_page_size).limit(safe_page_size).all()
    else:
        rows = query.order_by(HrEmployeeDocument.id.desc()).all()
    employee_ids = {int(row.employee_id) for row in rows if row.employee_id}
    names = {
        int(row.id): row.full_name
        for row in db.query(Employee.id, Employee.full_name).filter(
            Employee.factory_code == factory, Employee.id.in_(employee_ids)
        ).all()
    } if employee_ids else {}
    payload = [_document_dict(row, names.get(int(row.employee_id))) for row in rows]
    if not paginated:
        return payload
    aggregate = db.query(
        func.coalesce(func.sum(HrEmployeeDocument.size_bytes), 0),
        func.count(func.distinct(HrEmployeeDocument.employee_id)),
    ).filter(HrEmployeeDocument.factory_code == factory).one()
    expiry_cutoff = datetime.now(timezone.utc) + timedelta(days=30)
    expiring = query.filter(
        HrEmployeeDocument.expires_on.isnot(None),
        HrEmployeeDocument.expires_on < expiry_cutoff.date(),
    ).count()
    return {
        "rows": payload,
        "total": int(total or 0),
        "page": safe_page,
        "page_size": safe_page_size,
        "has_more": safe_page * safe_page_size < int(total or 0),
        "metrics": {
            "employee_folders": int(aggregate[1] or 0),
            "archive_size_bytes": int(aggregate[0] or 0),
            "expiring_in_30_days": int(expiring),
        },
    }


@router.post("/documents", status_code=201)
async def upload_document(
    db: DbSession,
    current: User = HrUser,
    employee_id: int = Form(...),
    category: str = Form(...),
    title: str = Form(...),
    expires_on: date | None = Form(default=None),
    file: UploadFile = File(...),
):
    factory = _factory(current); _employee(db, factory, employee_id)
    allowed_categories = {"employment_contract", "passport_id", "diploma", "certificate", "employment_order", "salary_amendment", "leave", "disciplinary", "training", "resignation", "other"}
    if category not in allowed_categories: raise HTTPException(422, "Unsupported HR document category")
    title = title.strip()
    if not title: raise HTTPException(422, "Document title is required")
    if len(title) > 255: raise HTTPException(422, "Document title is too long")
    content = await file.read(settings.HR_DOCUMENT_MAX_BYTES + 1)
    if not content or len(content) > settings.HR_DOCUMENT_MAX_BYTES: raise HTTPException(413, "Document is empty or too large")
    safe_original = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(file.filename or "document").name)[:255]
    stored = f"{factory.lower()}_{employee_id}_{secrets.token_hex(16)}{Path(safe_original).suffix.lower()[:12]}"
    root = Path(settings.HR_DOCUMENTS_DIR); root.mkdir(parents=True, exist_ok=True)
    target = root / stored
    with target.open("xb") as stream: stream.write(content)
    row = HrEmployeeDocument(factory_code=factory, employee_id=employee_id, category=category, title=title, original_name=safe_original, stored_name=stored, content_type=file.content_type, size_bytes=len(content), expires_on=expires_on, uploaded_by=current.id)
    db.add(row); db.flush(); log_action(db, current, "create", "HrEmployeeDocument", row.id, new_value={"employee_id": employee_id, "category": category, "title": title}); db.commit(); db.refresh(row)
    return _document_dict(row)


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, db: DbSession, current: User = HrUser):
    row = db.query(HrEmployeeDocument).filter(HrEmployeeDocument.id == document_id, HrEmployeeDocument.factory_code == _factory(current)).first()
    if not row: raise HTTPException(404, "Document not found")
    path = Path(settings.HR_DOCUMENTS_DIR) / row.stored_name
    if not path.is_file(): raise HTTPException(404, "Document file not found")
    return FileResponse(path, filename=row.original_name, media_type=row.content_type or "application/octet-stream", headers={"Cache-Control": "private, no-store"})


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: DbSession, current: User = HrUser):
    row = db.query(HrEmployeeDocument).filter(HrEmployeeDocument.id == document_id, HrEmployeeDocument.factory_code == _factory(current)).first()
    if not row: raise HTTPException(404, "Document not found")
    path = Path(settings.HR_DOCUMENTS_DIR) / row.stored_name
    db.delete(row); log_action(db, current, "delete", "HrEmployeeDocument", document_id); db.commit()
    try: path.unlink(missing_ok=True)
    except OSError: pass


@router.get("/attendance")
def hr_attendance(db: DbSession, current: User = HrUser, day: date | None = None):
    factory = _factory(current); selected = day or datetime.now(TASHKENT).date()
    start, end = _attendance_day_bounds(selected)
    default_hours = _load_hr_settings(db, factory).default_workday_hours
    employees = db.query(Employee).filter(Employee.factory_code == factory, Employee.status == "active").all()
    events = db.query(AttendanceEvent).filter(
        AttendanceEvent.factory_code == factory,
        AttendanceEvent.occurred_at >= start,
        AttendanceEvent.occurred_at < end,
        accepted_attendance_result(AttendanceEvent.result),
    ).order_by(AttendanceEvent.occurred_at).all()
    grouped: dict[str, list[AttendanceEvent]] = {}
    for event in events:
        if event.external_person_id: grouped.setdefault(event.external_person_id, []).append(event)
    rows = []
    for employee in employees:
        scans = grouped.get(str(employee.employee_no or ""), [])
        first = scans[0].occurred_at if scans else None; last = scans[-1].occurred_at if len(scans) > 1 else None
        worked = max(0, int((last - first).total_seconds() // 60)) if first and last else 0
        scheduled = _scheduled_minutes(employee.hr_profile_json, default_hours)
        rows.append({"employee_id": employee.id, "employee_no": employee.employee_no, "full_name": employee.full_name, "arrival_at": first, "departure_at": last, "worked_minutes": worked, "scheduled_minutes": scheduled, "variance_minutes": worked - scheduled, "status": "present" if scans else "absent"})
    return {"day": selected, "summary": {"employees": len(rows), "present": sum(1 for row in rows if row["status"] == "present"), "absent": sum(1 for row in rows if row["status"] == "absent"), "overtime_minutes": sum(max(0, row["variance_minutes"]) for row in rows)}, "rows": rows}


@router.get("/analytics")
def analytics(db: DbSession, current: User = HrUser):
    factory = _factory(current); employees = db.query(Employee).filter(Employee.factory_code == factory).all()
    active = [row for row in employees if row.status == "active"]
    salaries = [float(row.salary) for row in active if row.salary is not None]
    today = date.today(); tenures = [max(0, (today - row.joined_at.date()).days) for row in active if row.joined_at]
    gender: dict[str, int] = {}; ages: dict[str, int] = {"under_25": 0, "25_34": 0, "35_44": 0, "45_plus": 0}
    for row in active:
        profile = row.hr_profile_json or {}; label = str(profile.get("gender") or "not_specified"); gender[label] = gender.get(label, 0) + 1
        dob = profile.get("date_of_birth")
        if dob:
            try:
                age = (today - date.fromisoformat(str(dob))).days // 365
                ages["under_25" if age < 25 else "25_34" if age < 35 else "35_44" if age < 45 else "45_plus"] += 1
            except ValueError: pass
    return {"total_headcount": len(active), "inactive_headcount": len(employees) - len(active), "retention_rate": round((len(active) / len(employees) * 100), 1) if employees else 0, "average_tenure_years": round(sum(tenures) / len(tenures) / 365, 1) if tenures else 0, "average_salary": round(sum(salaries) / len(salaries), 2) if salaries else 0, "gender_distribution": gender, "age_distribution": ages}


@router.get("/calendar")
def list_calendar(
    db: DbSession,
    current: User = HrUser,
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
):
    query = db.query(HrCalendarEvent).filter(
        HrCalendarEvent.factory_code == _factory(current)
    )

    def serialize(row: HrCalendarEvent) -> dict:
        return {
            key: getattr(row, key)
            for key in (
                "id", "employee_id", "event_type", "title", "starts_at",
                "ends_at", "notes", "status",
            )
        }

    if page is None and page_size is None:
        rows = query.order_by(HrCalendarEvent.starts_at, HrCalendarEvent.id).all()
        return [serialize(row) for row in rows]
    size = page_size or 100
    current_page = page or 1
    offset = (current_page - 1) * size
    total = query.count()
    rows = (
        query.order_by(HrCalendarEvent.starts_at, HrCalendarEvent.id)
        .offset(offset)
        .limit(size)
        .all()
    )
    now = datetime.now(timezone.utc)
    metric_rows = (
        db.query(HrCalendarEvent.event_type, func.count(HrCalendarEvent.id))
        .filter(
            HrCalendarEvent.factory_code == _factory(current),
            HrCalendarEvent.status == "scheduled",
            HrCalendarEvent.starts_at >= now,
        )
        .group_by(HrCalendarEvent.event_type)
        .all()
    )
    by_type = {event_type: int(count) for event_type, count in metric_rows}
    upcoming = sum(by_type.values())
    return {
        "rows": [serialize(row) for row in rows],
        "total": total,
        "page": current_page,
        "page_size": size,
        "has_more": offset + size < total,
        "metrics": {
            "upcoming": upcoming,
            "contracts_expiring": by_type.get("contract_expiry", 0),
            "probation_ending": by_type.get("probation_end", 0),
            "training": by_type.get("training", 0),
        },
    }


@router.post("/calendar", status_code=201)
def create_calendar_event(payload: CalendarEventIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    if payload.employee_id is not None: _employee(db, factory, payload.employee_id)
    row = HrCalendarEvent(factory_code=factory, **payload.model_dump())
    db.add(row); db.flush(); log_action(db, current, "create", "HrCalendarEvent", row.id, new_value={"title": row.title, "event_type": row.event_type}); db.commit(); db.refresh(row)
    return {"id": row.id}


def _settings_key(factory: str) -> str:
    return f"hr.settings.{factory.lower()}"


@router.get("/settings")
def get_hr_settings(db: DbSession, current: User = HrUser):
    return _load_hr_settings(db, _factory(current))


@router.put("/settings")
def put_hr_settings(payload: HrSettingsIn, db: DbSession, current: User = HrUser):
    key = _settings_key(_factory(current)); row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row: row = SystemSetting(key=key, value_json={}); db.add(row)
    row.value_json = payload.model_dump(); log_action(db, current, "update", "HrSettings", row.id, new_value=row.value_json); db.commit()
    return row.value_json
