"""Employee row persistence within the caller-owned transaction."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.people import EmployeeStatus
from app.schemas.core import Employee


def insert_employee(
    db: Session,
    *,
    factory_code: str,
    user_id: int | None,
    employee_no: str | None,
    full_name: str,
    department_id: int | None,
    position: str | None,
    phone: str | None,
    salary: Decimal | None,
    status: EmployeeStatus,
    joined_at: datetime | None,
    manager_employee_id: int | None,
    hr_position_id: int | None,
    hr_profile_json: dict,
) -> Employee:
    row = Employee(
        factory_code=factory_code,
        user_id=user_id,
        employee_no=employee_no,
        full_name=full_name,
        department_id=department_id,
        position=position,
        phone=phone,
        salary=salary,
        status=status.value,
        joined_at=joined_at,
        manager_employee_id=manager_employee_id,
        hr_position_id=hr_position_id,
        hr_profile_json=hr_profile_json,
    )
    db.add(row)
    db.flush()
    return row
