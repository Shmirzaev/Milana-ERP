"""Department operations; the supplied Session owns one outer transaction."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.catalog.catalog import DepartmentIn
from app.models.audit_service import log_action
from app.schemas import Department, Employee, User, WorkOrder
from app.schemas.people.department_persistence import delete_department_row, insert_department, update_department_values


def create_department(payload: DepartmentIn, db: Session, current: User) -> Department:
    department = insert_department(db, name=payload.name, code=payload.code)
    db.flush()
    log_action(db, current, "create", "Department", department.id, new_value={"name": department.name})
    db.commit()
    db.refresh(department)
    return department


def update_department(
    department_id: int, payload: DepartmentIn, db: Session, current: User,
) -> Department:
    d = db.get(Department, department_id)
    if not d:
        raise HTTPException(404, "Department not found")

    name = payload.name.strip()
    code = payload.code.strip().upper()
    if not name or not code:
        raise HTTPException(400, "name and code are required")

    name_exists = db.query(Department).filter(Department.name == name, Department.id != department_id).first()
    if name_exists:
        raise HTTPException(400, "Department name already exists")
    code_exists = db.query(Department).filter(Department.code == code, Department.id != department_id).first()
    if code_exists:
        raise HTTPException(400, "Department code already exists")

    old = {"name": d.name, "code": d.code}
    update_department_values(db, d, name=name, code=code)
    log_action(db, current, "update", "Department", d.id, old_value=old, new_value={"name": d.name, "code": d.code})
    db.commit()
    db.refresh(d)
    return d


def delete_department(department_id: int, db: Session, current: User) -> None:
    d = db.get(Department, department_id)
    if not d:
        raise HTTPException(404, "Department not found")

    if db.query(User).filter(User.department_id == department_id).first():
        raise HTTPException(409, "Department is assigned to users. Reassign users before delete.")
    if db.query(Employee).filter(Employee.department_id == department_id).first():
        raise HTTPException(409, "Department is assigned to employees. Reassign employees before delete.")
    if db.query(WorkOrder).filter(WorkOrder.department_id == department_id).first():
        raise HTTPException(409, "Department is used by work orders. Delete is blocked.")

    delete_department_row(db, d)
    log_action(db, current, "delete", "Department", department_id)
    db.commit()
