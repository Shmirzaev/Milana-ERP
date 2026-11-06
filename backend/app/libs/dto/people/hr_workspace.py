from datetime import date, datetime
from math import isfinite

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

MAX_INT4 = 2_147_483_647


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


class OrgUnitIn(BaseModel):
    parent_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    manager_employee_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    unit_type: str = Field(pattern="^(company|factory|department|section|team)$")
    name: str = Field(min_length=1, max_length=160)
    code: str | None = Field(default=None, max_length=48)
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "Organization unit name")


MAX_POSITION_SALARY = 999_999_999_999.99


class PositionIn(BaseModel):
    org_unit_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    name: str = Field(min_length=1, max_length=160)
    job_description: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    qualification_level: str | None = None
    grade_level: str | None = None
    salary_min: float | None = Field(default=None, ge=0, le=MAX_POSITION_SALARY, allow_inf_nan=False)
    salary_max: float | None = Field(default=None, ge=0, le=MAX_POSITION_SALARY, allow_inf_nan=False)
    approved_count: int = Field(default=0, ge=0)
    is_active: bool = True

    @field_validator("salary_min", "salary_max", mode="before")
    @classmethod
    def validate_finite_salary(cls, value):
        if isinstance(value, float) and not isfinite(value):
            raise HTTPException(422, "Salary must be a finite number")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _required_text(value, "Position name")

    @model_validator(mode="after")
    def validate_salary_range(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Minimum salary cannot exceed maximum salary")
        return self


class CandidateIn(BaseModel):
    position_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    department_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    full_name: str = Field(min_length=1, max_length=255)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, pattern="^(male|female|other)$")
    nationality: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    passport_number: str | None = Field(default=None, max_length=32)
    passport_issued_by: str | None = Field(default=None, max_length=255)
    passport_issue_date: date | None = None
    passport_expiry_date: date | None = None
    pinfl: str | None = Field(default=None, pattern="^[0-9]{14}$")
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = None
    source: str | None = None
    stage: str = Field(default="applied", pattern="^(applied|screening|interview|offer|hired|rejected)$")
    applied_on: date | None = None
    interview_at: datetime | None = None
    notes: str | None = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value: str) -> str:
        return _required_text(value, "Candidate name")

    @model_validator(mode="after")
    def validate_passport_dates(self):
        if (
            self.passport_issue_date is not None
            and self.passport_expiry_date is not None
            and self.passport_expiry_date < self.passport_issue_date
        ):
            raise ValueError("Passport expiry date cannot precede its issue date")
        return self


class CalendarEventIn(BaseModel):
    employee_id: int | None = Field(default=None, gt=0, le=MAX_INT4)
    event_type: str = Field(pattern="^(birthday|contract_expiry|probation_end|leave|training|interview|medical_check|certification|performance_review|other)$")
    title: str = Field(min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime | None = None
    notes: str | None = None
    status: str = Field(default="scheduled", pattern="^(scheduled|completed|cancelled)$")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _required_text(value, "Calendar event title")

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.ends_at is None:
            return self
        starts_aware = self.starts_at.tzinfo is not None and self.starts_at.utcoffset() is not None
        ends_aware = self.ends_at.tzinfo is not None and self.ends_at.utcoffset() is not None
        if starts_aware != ends_aware:
            raise ValueError("Calendar start and end must use matching timezone formats")
        if self.ends_at < self.starts_at:
            raise ValueError("Calendar end cannot precede its start")
        return self



class HrSettingsIn(BaseModel):
    company_name: str = "Milana Premium"
    default_workday_hours: float = Field(default=8, gt=0, le=24, allow_inf_nan=False)
    default_monthly_hours: float = Field(default=176, ge=0, le=744, allow_inf_nan=False)
    probation_days: int = Field(default=90, ge=0, le=730)
    contract_warning_days: int = Field(default=30, ge=0, le=365)
    weekend_days: list[int] = Field(default_factory=lambda: [6, 7])

    @field_validator("default_workday_hours", "default_monthly_hours", mode="before")
    @classmethod
    def validate_finite_hours(cls, value):
        if isinstance(value, float) and not isfinite(value):
            raise HTTPException(422, "Scheduled hours must be finite")
        return value

