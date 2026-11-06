"""Department operations; the supplied Session owns one outer transaction."""

from sqlalchemy.orm import Session

from app.libs.dto.catalog.catalog import DepartmentIn
from app.models.audit_service import log_action
from app.schemas import Department, User
from app.schemas.people.department_persistence import insert_department


def create_department(payload: DepartmentIn, db: Session, current: User) -> Department:
    department = insert_department(db, name=payload.name, code=payload.code)
    db.flush()
    log_action(db, current, "create", "Department", department.id, new_value={"name": department.name})
    db.commit()
    db.refresh(department)
    return department
