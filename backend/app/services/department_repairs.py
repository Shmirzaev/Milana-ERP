from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Department


def repair_department_name(db: Session, department_id: int, raw_name: object) -> tuple[Department, str]:
    """Apply the narrowly approved Data Console repair for a department name."""
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(404, "Department not found")
    if not isinstance(raw_name, str):
        raise HTTPException(422, "Department name must be a non-empty string")

    name = raw_name.strip()
    if not name:
        raise HTTPException(422, "Department name must be a non-empty string")
    if len(name) > 128:
        raise HTTPException(422, "Department name must be at most 128 characters")
    duplicate = (
        db.query(Department.id)
        .filter(Department.name == name, Department.id != department_id)
        .first()
    )
    if duplicate is not None:
        raise HTTPException(409, "Department name already exists")

    previous_name = department.name
    department.name = name
    return department, previous_name


def deactivate_department(db: Session, department_id: int) -> tuple[Department, bool]:
    """Mark a department inactive without removing its historical references."""
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(404, "Department not found")
    if not department.is_active:
        return department, False
    department.is_active = False
    return department, True
