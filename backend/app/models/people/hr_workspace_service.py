"""HR workspace operations; each service owns its supplied transaction."""

from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.people.hr_workspace import OrgUnitIn, PositionIn
from app.models.factory_scope_service import factory_for_department, selected_factory_code
from app.schemas import Department, Employee, HrOrgUnit, HrPosition, User
from app.schemas.people.hr_workspace_persistence import insert_org_unit, delete_org_unit_row, insert_position, update_position_row


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
