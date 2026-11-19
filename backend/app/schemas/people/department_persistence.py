"""Department writes in the caller's transaction."""

from sqlalchemy.orm import Session

from app.schemas import Department


def insert_department(db: Session, *, name: str, code: str) -> Department:
    department = Department(name=name, code=code)
    db.add(department)
    return department


def update_department_values(db: Session, department: Department, *, name: str, code: str) -> None:
    department.name = name
    department.code = code


def delete_department_row(db: Session, department: Department) -> None:
    db.delete(department)
