from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class HrOrgUnit(Base, PkMixin, TimestampMixin):
    __tablename__ = "hr_org_units"
    __table_args__ = (
        UniqueConstraint("factory_code", "unit_type", "name", "parent_id", name="uq_hr_org_unit_path"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("hr_org_units.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    manager_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"), index=True)
    unit_type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str | None] = mapped_column(String(48))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class HrPosition(Base, PkMixin, TimestampMixin):
    __tablename__ = "hr_positions"

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    org_unit_id: Mapped[int | None] = mapped_column(ForeignKey("hr_org_units.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    job_description: Mapped[str | None] = mapped_column(Text)
    required_skills_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    qualification_level: Mapped[str | None] = mapped_column(String(80))
    grade_level: Mapped[str | None] = mapped_column(String(80))
    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2))
    approved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class HrEmployeeDocument(Base, PkMixin):
    __tablename__ = "hr_employee_documents"

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class HrRecruitmentCandidate(Base, PkMixin, TimestampMixin):
    __tablename__ = "hr_recruitment_candidates"

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("hr_positions.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    middle_name: Mapped[str | None] = mapped_column(String(100))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(16))
    nationality: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(255))
    passport_number: Mapped[str | None] = mapped_column(String(32))
    passport_issued_by: Mapped[str | None] = mapped_column(String(255))
    passport_issue_date: Mapped[date | None] = mapped_column(Date)
    passport_expiry_date: Mapped[date | None] = mapped_column(Date)
    pinfl: Mapped[str | None] = mapped_column(String(14), index=True)
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="applied", server_default="applied", index=True)
    applied_on: Mapped[date | None] = mapped_column(Date)
    interview_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class HrCalendarEvent(Base, PkMixin, TimestampMixin):
    __tablename__ = "hr_calendar_events"

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled", server_default="scheduled")
