from __future__ import annotations

import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from functools import partial
from math import isfinite
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func

from app.core.config import settings
from app.core.deps import DbSession, require_permissions
from app.schemas import (
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
from app.models.audit_service import log_action
from app.models.people import hr_workspace_service
from app.libs.dto.people.hr_workspace import OrgUnitIn as OrgUnitIn, PositionIn as PositionIn, CandidateIn as CandidateIn, _required_text as _required_text
from app.models.people.hr_workspace_service import (
    _factory as _factory, _employee as _employee, _department as _department,
    _org_unit as _org_unit, _validate_org_unit_links as _validate_org_unit_links,
    _validate_position_links as _validate_position_links,
    _validate_candidate_links as _validate_candidate_links,
)
from app.models.attendance_reports_service import TASHKENT
from app.models.attendance_event_policy_service import accepted_attendance_result


router = APIRouter(prefix="/hr", tags=["hr-workspace"])
HrUser = Depends(require_permissions("hr.employees", "*"))
MAX_INT4 = 2_147_483_647


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
    return hr_workspace_service.create_org_unit(payload, db, current, audit=log_action)


@router.delete("/organization/{unit_id}", status_code=204)
def delete_org_unit(unit_id: int, db: DbSession, current: User = HrUser):
    return hr_workspace_service.delete_org_unit(unit_id, db, current, audit=log_action)


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
    return _position_dict(hr_workspace_service.create_position(payload, db, current, audit=log_action))


@router.patch("/positions/{position_id}")
def update_position(position_id: int, payload: PositionIn, db: DbSession, current: User = HrUser):
    return _position_dict(hr_workspace_service.update_position(position_id, payload, db, current, audit=log_action))


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


@router.post("/recruitment", status_code=201)
def create_candidate(payload: CandidateIn, db: DbSession, current: User = HrUser):
    return hr_workspace_service.create_candidate(payload, db, current, audit=log_action)


@router.patch("/recruitment/{candidate_id}")
def update_candidate(candidate_id: int, payload: CandidateIn, db: DbSession, current: User = HrUser):
    return hr_workspace_service.update_candidate(candidate_id, payload, db, current, audit=log_action)


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


def _write_new_hr_document(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(content)


def _require_hr_upload_employee(db, factory: str, employee_id: int) -> None:
    """Re-verify the employee and its factory on the session that writes."""
    _employee(db, factory, employee_id)


def _create_hr_upload_document(
    db,
    *,
    factory: str,
    employee_id: int,
    category: str,
    title: str,
    original_name: str,
    stored_name: str,
    content_type: str | None,
    size_bytes: int,
    expires_on: date | None,
    actor_id: int,
) -> dict:
    _require_hr_upload_employee(db, factory, employee_id)
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(401, "Inactive or unknown user")
    row = HrEmployeeDocument(
        factory_code=factory,
        employee_id=employee_id,
        category=category,
        title=title,
        original_name=original_name,
        stored_name=stored_name,
        content_type=content_type,
        size_bytes=size_bytes,
        expires_on=expires_on,
        uploaded_by=actor_id,
    )
    db.add(row)
    db.flush()
    log_action(
        db,
        actor,
        "create",
        "HrEmployeeDocument",
        row.id,
        new_value={"employee_id": employee_id, "category": category, "title": title},
    )
    db.refresh(row)
    return _document_dict(row)


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
    from app.models.image_storage_service import (
        UploadCommitState,
        UploadFileWriteState,
        run_blocking_to_completion,
        run_upload_db_work,
        run_upload_file_write,
        upload_processing_slot,
        upload_session_factory,
    )

    factory = _factory(current)
    actor_id = int(current.id)
    worker_sessions = upload_session_factory(db)
    # Pre-flight: an employee outside this factory must fail before a body is
    # buffered or written.
    await run_upload_db_work(
        worker_sessions,
        partial(_require_hr_upload_employee, factory=factory, employee_id=employee_id),
    )
    allowed_categories = {"employment_contract", "passport_id", "diploma", "certificate", "employment_order", "salary_amendment", "leave", "disciplinary", "training", "resignation", "other"}
    if category not in allowed_categories: raise HTTPException(422, "Unsupported HR document category")
    title = title.strip()
    if not title: raise HTTPException(422, "Document title is required")
    if len(title) > 255: raise HTTPException(422, "Document title is too long")
    safe_original = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(file.filename or "document").name)[:255]
    stored = f"{factory.lower()}_{employee_id}_{secrets.token_hex(16)}{Path(safe_original).suffix.lower()[:12]}"
    target = Path(settings.HR_DOCUMENTS_DIR) / stored
    write_state = UploadFileWriteState()
    commit_state = UploadCommitState()
    try:
        async with upload_processing_slot():
            content = await file.read(settings.HR_DOCUMENT_MAX_BYTES + 1)
            if not content or len(content) > settings.HR_DOCUMENT_MAX_BYTES:
                raise HTTPException(413, "Document is empty or too large")
            await run_upload_file_write(partial(_write_new_hr_document, target, content), write_state)
        # The write re-checks the employee on the worker's own session, so an
        # employee moved to another factory mid-upload cannot receive a file.
        document = await run_upload_db_work(
            worker_sessions,
            partial(
                _create_hr_upload_document,
                factory=factory,
                employee_id=employee_id,
                category=category,
                title=title,
                original_name=safe_original,
                stored_name=stored,
                content_type=file.content_type,
                size_bytes=len(content),
                expires_on=expires_on,
                actor_id=actor_id,
            ),
            commit=True,
            commit_state=commit_state,
        )
    except BaseException:
        if write_state.created and not commit_state.committed:
            await run_blocking_to_completion(partial(target.unlink, True))
        raise
    return document


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
def list_calendar(db: DbSession, current: User = HrUser):
    rows = db.query(HrCalendarEvent).filter(HrCalendarEvent.factory_code == _factory(current)).order_by(HrCalendarEvent.starts_at).all()
    return [{key: getattr(row, key) for key in ("id", "employee_id", "event_type", "title", "starts_at", "ends_at", "notes", "status")} for row in rows]


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
