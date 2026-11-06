"""Schema-owned employee insert for the caller's transaction."""

from sqlalchemy.orm import Session

from app.schemas import Employee


def insert_employee(session: Session, *, factory_code: str, values: dict) -> Employee:
    employee = Employee(factory_code=factory_code, **values)
    session.add(employee)
    return employee


def update_employee_fields(session: Session, *, employee: Employee, changes: dict) -> None:
    for key, value in changes.items():
        setattr(employee, key, value)
