"""HR workspace operations; each service owns its supplied transaction."""

from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path
import re
import secrets

from fastapi import HTTPException, UploadFile

from app.core.config import settings
from sqlalchemy.orm import Session

from app.libs.dto.people.hr_workspace import OrgUnitIn, PositionIn, CandidateIn
from app.models.factory_scope_service import factory_for_department, selected_factory_code
from app.schemas import Department, Employee, HrOrgUnit, HrPosition, HrRecruitmentCandidate, HrEmployeeDocument, User
from app.schemas.people.hr_workspace_persistence import insert_org_unit, delete_org_unit_row, insert_position, update_position_row, insert_candidate, update_candidate_row, insert_document


def _factory(current: User) -> str:
    return selected_factory_code(current)


def _employee(db: Session, factory: str, employee_id: int) -> Employee:
    row = db.query(Employee).filter(Employee.id == employee_id, Employee.factory_code == factory).first()
    if not row:
        raise HTTPException(404, "Employee not found")
    return row


def _department(db: Session, factory: str, department_id: int) -> Department:
    row = db.get(Department, department_id)
    if not row:
        raise HTTPException(404, "Department not found")
    department_factory = factory_for_department(row.code)
    if department_factory and department_factory != factory:
        raise HTTPException(409, "Department belongs to another factory")
    return row


def _org_unit(db: Session, factory: str, unit_id: int) -> HrOrgUnit:
    row = db.query(HrOrgUnit).filter(HrOrgUnit.id == unit_id, HrOrgUnit.factory_code == factory).first()
    if not row:
        raise HTTPException(404, "Organization unit not found")
    return row


def _validate_org_unit_links(payload: OrgUnitIn, db: Session, factory: str) -> None:
    if payload.parent_id is not None:
        _org_unit(db, factory, payload.parent_id)
    if payload.department_id is not None:
        _department(db, factory, payload.department_id)
    if payload.manager_employee_id is not None:
        _employee(db, factory, payload.manager_employee_id)


def create_org_unit(payload: OrgUnitIn, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    _validate_org_unit_links(payload, db, factory)
    row = insert_org_unit(db, factory_code=factory, values=payload.model_dump())
    db.flush()
    audit(db, current, "create", "HrOrgUnit", row.id, new_value={"name": row.name, "unit_type": row.unit_type})
    db.commit(); db.refresh(row)
    return {"id": row.id}


def delete_org_unit(unit_id: int, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    row = db.query(HrOrgUnit).filter(HrOrgUnit.id == unit_id, HrOrgUnit.factory_code == factory).first()
    if not row: raise HTTPException(404, "Organization unit not found")
    delete_org_unit_row(db, row)
    audit(db, current, "delete", "HrOrgUnit", unit_id)
    db.commit()


def _validate_position_links(payload: PositionIn, db: Session, factory: str) -> None:
    if payload.org_unit_id is not None:
        _org_unit(db, factory, payload.org_unit_id)
    if payload.department_id is not None:
        _department(db, factory, payload.department_id)


def create_position(payload: PositionIn, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    _validate_position_links(payload, db, factory)
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    row = insert_position(db, factory_code=factory, values=values)
    db.flush(); audit(db, current, "create", "HrPosition", row.id, new_value={"name": row.name}); db.commit(); db.refresh(row)
    return row


def update_position(position_id: int, payload: PositionIn, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    row = db.query(HrPosition).filter(HrPosition.id == position_id, HrPosition.factory_code == factory).first()
    if not row: raise HTTPException(404, "Position not found")
    _validate_position_links(payload, db, factory)
    values = payload.model_dump(); values["required_skills_json"] = values.pop("required_skills")
    update_position_row(db, row=row, values=values)
    audit(db, current, "update", "HrPosition", row.id, new_value=values); db.commit(); db.refresh(row)
    return row


def _validate_candidate_links(payload: CandidateIn, db: Session, factory: str, candidate_id: int | None = None) -> None:
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


def create_candidate(payload: CandidateIn, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    _validate_candidate_links(payload, db, factory)
    row = insert_candidate(db, factory_code=factory, values=payload.model_dump())
    db.flush(); audit(db, current, "create", "HrRecruitmentCandidate", row.id, new_value={"full_name": row.full_name}); db.commit(); db.refresh(row)
    return {"id": row.id}


def update_candidate(candidate_id: int, payload: CandidateIn, db: Session, current: User, *, audit: Callable):
    factory = _factory(current)
    row = db.query(HrRecruitmentCandidate).filter(HrRecruitmentCandidate.id == candidate_id, HrRecruitmentCandidate.factory_code == factory).first()
    if not row: raise HTTPException(404, "Candidate not found")
    _validate_candidate_links(payload, db, factory, candidate_id)
    update_candidate_row(db, row=row, values=payload.model_dump())
    audit(db, current, "update", "HrRecruitmentCandidate", row.id, new_value={"stage": row.stage}); db.commit()
    return {"id": row.id}


def _document_dict(row: HrEmployeeDocument, employee_name: str | None = None) -> dict:
    return {
        "id": row.id, "employee_id": row.employee_id, "employee_name": employee_name,
        "category": row.category, "title": row.title, "original_name": row.original_name,
        "content_type": row.content_type, "size_bytes": row.size_bytes,
        "expires_on": row.expires_on, "created_at": row.created_at,
        "download_url": f"/api/hr/documents/{row.id}/download",
    }


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
    audit: Callable,
) -> dict:
    _require_hr_upload_employee(db, factory, employee_id)
    actor = db.get(User, actor_id)
    if not actor:
        raise HTTPException(401, "Inactive or unknown user")
    row = insert_document(db, values={
        "factory_code": factory, "employee_id": employee_id, "category": category,
        "title": title, "original_name": original_name, "stored_name": stored_name,
        "content_type": content_type, "size_bytes": size_bytes, "expires_on": expires_on,
        "uploaded_by": actor_id,
    })
    db.flush()
    audit(
        db,
        actor,
        "create",
        "HrEmployeeDocument",
        row.id,
        new_value={"employee_id": employee_id, "category": category, "title": title},
    )
    db.refresh(row)
    return _document_dict(row)


async def upload_document(
    db: Session, current: User, employee_id: int, category: str, title: str,
    expires_on: date | None, file: UploadFile, *, audit: Callable, write_document: Callable,
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
            await run_upload_file_write(partial(write_document, target, content), write_state)
        # The write re-checks the employee on the worker's own session, so an
        # employee moved to another factory mid-upload cannot receive a file.
        document = await run_upload_db_work(
            worker_sessions,
            partial(
                _create_hr_upload_document,
                audit=audit,
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
