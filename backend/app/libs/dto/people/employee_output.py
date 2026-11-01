"""Response contract for employee creation."""

from datetime import datetime

from app.libs.dto.common import ORMModel
from app.libs.enums.people import EmployeeStatus


class EmployeeCreateOut(ORMModel):
    id: int
    factory_code: str
    employee_no: str | None
    user_id: int | None
    full_name: str
    department_id: int | None
    position: str | None
    status: EmployeeStatus
    joined_at: datetime | None
    manager_employee_id: int | None
    hr_position_id: int | None
    phone: str | None
    salary: float | None
    hr_profile_json: dict
