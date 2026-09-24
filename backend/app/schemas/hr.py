from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EmployeeOut(BaseModel):
    id: int
    factory_code: str
    employee_no: str | None
    user_id: int | None
    full_name: str
    department_id: int | None
    position: str | None
    status: str
    joined_at: datetime | None
    manager_employee_id: int | None
    hr_position_id: int | None
    phone: str | None = None
    salary: float | None = None
    hr_profile_json: dict[str, Any] | None = None
    manager_name: str | None = None


class EmployeePageOut(BaseModel):
    rows: list[EmployeeOut]
    total: int
    page: int
    page_size: int
    has_more: bool
    active_total: int
    inactive_total: int
    profile_coverage_percent: int | None = None
    search: str
