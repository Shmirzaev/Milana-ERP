"""Input contracts for employee operations."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.libs.enums.people import EmployeeStatus


def normalize_employee_no(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class EmployeeProfileJson(BaseModel):
    """Persisted fields supported by the employee profile editor and reports."""

    model_config = ConfigDict(extra="forbid", strict=True)

    photo_url: str | None = None
    date_of_birth: str | None = None
    gender: str | None = None
    email: str | None = None
    address: str | None = None
    emergency_contact: str | None = None
    nationality: str | None = None
    company: str | None = None
    branch: str | None = None
    section: str | None = None
    grade_level: str | None = None
    employment_type: str | None = None
    probation_end: str | None = None
    work_schedule: str | None = None
    shift: str | None = None
    workplace: str | None = None
    scheduled_daily_hours: str | int | float | None = None
    rate_type: str | None = None
    bonus_scheme: str | None = None
    bank_details: str | None = None
    payroll_id: str | None = None


class EmployeeCreateIn(BaseModel):
    user_id: Optional[int] = None
    employee_no: Optional[str] = Field(default=None, max_length=32, pattern=r"^\d+$")
    full_name: str
    department_id: Optional[int] = None
    position: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[Decimal] = Field(default=None, allow_inf_nan=True)
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    joined_at: Optional[datetime] = None
    manager_employee_id: Optional[int] = None
    hr_position_id: Optional[int] = None
    hr_profile_json: dict = Field(default_factory=dict)

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_number(cls, value: object) -> str | None:
        return normalize_employee_no(value)
