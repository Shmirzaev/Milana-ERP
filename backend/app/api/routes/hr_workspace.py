from __future__ import annotations

import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.models import (
    AttendanceEvent,
    AttendancePerson,
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
from app.services.factory_scope import selected_factory_code


router = APIRouter(prefix="/hr", tags=["hr-workspace"])
HrUser = Depends(require_permissions("hr.employees", "*"))


class OrgUnitIn(BaseModel):
    parent_id: int | None = None
    department_id: int | None = None
    manager_employee_id: int | None = None
    unit_type: str = Field(pattern="^(company|factory|department|section|team)$")
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=48)
    sort_order: int = 0


class PositionIn(BaseModel):
    org_unit_id: int | None = None
    department_id: int | None = None
    name: str = Field(min_length=1, max_length=160)
    job_description: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    qualification_level: str | None = None
    grade_level: str | None = None
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    approved_count: int = Field(default=0, ge=0)
    is_active: bool = True


class CandidateIn(BaseModel):
    position_id: int | None = None
    department_id: int | None = None
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


class CalendarEventIn(BaseModel):
    employee_id: int | None = None
    event_type: str = Field(pattern="^(birthday|contract_expiry|probation_end|leave|training|interview|medical_check|certification|performance_review|other)$")
    title: str = Field(min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime | None = None
    notes: str | None = None
    status: str = Field(default="scheduled", pattern="^(scheduled|completed|cancelled)$")


class HrSettingsIn(BaseModel):
    company_name: str = "Milana Premium"
    default_workday_hours: float = Field(default=8, gt=0, le=24)
    default_monthly_hours: float = Field(default=176, ge=0, le=744)
    probation_days: int = Field(default=90, ge=0, le=730)
    contract_warning_days: int = Field(default=30, ge=0, le=365)
    weekend_days: list[int] = Field(default_factory=lambda: [6, 7])


def _factory(current: User) -> str:
    return selected_factory_code(current)


def _employee(db: DbSession, factory: str, employee_id: int) -> Employee:
    row = db.query(Employee).filter(Employee.id == employee_id, Employee.factory_code == factory).first()
    if not row:
        raise HTTPException(404, "Employee not found")
    return row


def _position_dict(row: HrPosition, occupied: int = 0) -> dict:
    return {
        "id": row.id,
        "org_unit_id": row.org_unit_id,
        "department_id": row.department_id,
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
    if payload.parent_id and not db.query(HrOrgUnit).filter(HrOrgUnit.id == payload.parent_id, HrOrgUnit.factory_code == factory).first():
        raise HTTPException(404, "Parent organization unit not found")
    if payload.manager_employee_id:
        _employee(db, factory, payload.manager_employee_id)
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
    return [_position_dict(row, occupied.get(row.id, 0)) for row in rows]


@router.post("/positions", status_code=201)
def create_position(payload: PositionIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    if payload.salary_min is not None and payload.salary_max is not None and payload.salary_min > payload.salary_max:
        raise HTTPException(422, "Minimum salary cannot exceed maximum salary")
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    row = HrPosition(factory_code=factory, **values)
    db.add(row); db.flush(); log_action(db, current, "create", "HrPosition", row.id, new_value={"name": row.name}); db.commit(); db.refresh(row)
    return _position_dict(row)


@router.patch("/positions/{position_id}")
def update_position(position_id: int, payload: PositionIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    row = db.query(HrPosition).filter(HrPosition.id == position_id, HrPosition.factory_code == factory).first()
    if not row: raise HTTPException(404, "Position not found")
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    for key, value in values.items(): setattr(row, key, value)
    log_action(db, current, "update", "HrPosition", row.id, new_value=values); db.commit(); db.refresh(row)
    return _position_dict(row)


@router.get("/recruitment")
def list_candidates(db: DbSession, current: User = HrUser):
    rows = db.query(HrRecruitmentCandidate).filter(HrRecruitmentCandidate.factory_code == _factory(current)).order_by(HrRecruitmentCandidate.id.desc()).all()
    fields = (
        "id", "position_id", "department_id", "full_name", "first_name", "last_name", "middle_name",
        "date_of_birth", "gender", "nationality", "country", "region", "district", "address",
        "passport_number", "passport_issued_by", "passport_issue_date", "passport_expiry_date", "pinfl",
        "phone", "email", "source", "stage", "applied_on", "interview_at", "notes",
    )
    return [{key: getattr(row, key) for key in fields} for row in rows]


def _validate_candidate_links(payload: CandidateIn, db: DbSession, factory: str, candidate_id: int | None = None) -> None:
    if payload.position_id and not db.query(HrPosition).filter(
        HrPosition.id == payload.position_id, HrPosition.factory_code == factory,
    ).first():
        raise HTTPException(404, "Staffing position not found")
    if payload.department_id and not db.query(Department).filter(Department.id == payload.department_id).first():
        raise HTTPException(404, "Department not found")
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
def list_documents(db: DbSession, current: User = HrUser):
    factory = _factory(current)
    names = {row.id: row.full_name for row in db.query(Employee).filter(Employee.factory_code == factory).all()}
    rows = db.query(HrEmployeeDocument).filter(HrEmployeeDocument.factory_code == factory).order_by(HrEmployeeDocument.id.desc()).all()
    return [_document_dict(row, names.get(row.employee_id)) for row in rows]


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
    content = await file.read(settings.HR_DOCUMENT_MAX_BYTES + 1)
    if not content or len(content) > settings.HR_DOCUMENT_MAX_BYTES: raise HTTPException(413, "Document is empty or too large")
    safe_original = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(file.filename or "document").name)[:255]
    stored = f"{factory.lower()}_{employee_id}_{secrets.token_hex(16)}{Path(safe_original).suffix.lower()[:12]}"
    root = Path(settings.HR_DOCUMENTS_DIR); root.mkdir(parents=True, exist_ok=True)
    target = root / stored
    with target.open("xb") as stream: stream.write(content)
    row = HrEmployeeDocument(factory_code=factory, employee_id=employee_id, category=category, title=title.strip(), original_name=safe_original, stored_name=stored, content_type=file.content_type, size_bytes=len(content), expires_on=expires_on, uploaded_by=current.id)
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
    factory = _factory(current); selected = day or datetime.now(timezone.utc).date()
    start = datetime.combine(selected, datetime.min.time(), tzinfo=timezone.utc); end = start + timedelta(days=1)
    employees = db.query(Employee).filter(Employee.factory_code == factory, Employee.status == "active").all()
    events = db.query(AttendanceEvent).filter(AttendanceEvent.factory_code == factory, AttendanceEvent.occurred_at >= start, AttendanceEvent.occurred_at < end).order_by(AttendanceEvent.occurred_at).all()
    grouped: dict[str, list[AttendanceEvent]] = {}
    for event in events:
        if event.external_person_id: grouped.setdefault(event.external_person_id, []).append(event)
    rows = []
    for employee in employees:
        scans = grouped.get(str(employee.employee_no or ""), [])
        first = scans[0].occurred_at if scans else None; last = scans[-1].occurred_at if len(scans) > 1 else None
        worked = max(0, int((last - first).total_seconds() // 60)) if first and last else 0
        scheduled = float((employee.hr_profile_json or {}).get("scheduled_daily_hours") or 8) * 60
        rows.append({"employee_id": employee.id, "employee_no": employee.employee_no, "full_name": employee.full_name, "arrival_at": first, "departure_at": last, "worked_minutes": worked, "scheduled_minutes": int(scheduled), "variance_minutes": worked - int(scheduled), "status": "present" if scans else "absent"})
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
def list_calendar(db: DbSession, current: User = HrUser):
    rows = db.query(HrCalendarEvent).filter(HrCalendarEvent.factory_code == _factory(current)).order_by(HrCalendarEvent.starts_at).all()
    return [{key: getattr(row, key) for key in ("id", "employee_id", "event_type", "title", "starts_at", "ends_at", "notes", "status")} for row in rows]


@router.post("/calendar", status_code=201)
def create_calendar_event(payload: CalendarEventIn, db: DbSession, current: User = HrUser):
    factory = _factory(current)
    if payload.employee_id: _employee(db, factory, payload.employee_id)
    row = HrCalendarEvent(factory_code=factory, **payload.model_dump())
    db.add(row); db.flush(); log_action(db, current, "create", "HrCalendarEvent", row.id, new_value={"title": row.title, "event_type": row.event_type}); db.commit(); db.refresh(row)
    return {"id": row.id}


def _settings_key(factory: str) -> str:
    return f"hr.settings.{factory.lower()}"


@router.get("/settings")
def get_hr_settings(db: DbSession, current: User = HrUser):
    row = db.query(SystemSetting).filter(SystemSetting.key == _settings_key(_factory(current))).first()
    return HrSettingsIn(**(row.value_json if row else {}))


@router.put("/settings")
def put_hr_settings(payload: HrSettingsIn, db: DbSession, current: User = HrUser):
    key = _settings_key(_factory(current)); row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not row: row = SystemSetting(key=key, value_json={}); db.add(row)
    row.value_json = payload.model_dump(); log_action(db, current, "update", "HrSettings", row.id, new_value=row.value_json); db.commit()
    return row.value_json
