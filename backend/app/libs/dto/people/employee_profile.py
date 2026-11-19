from pydantic import BaseModel, ConfigDict


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
