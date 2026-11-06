"""Reporting-only roll sightings. Never participates in stock accounting."""
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin


class FabricScan(Base, PkMixin):
    __tablename__ = "fabric_scans"
    __table_args__ = (
        UniqueConstraint("department", "report_date", "batch_id", "roll_number", "direction", name="uq_fabric_scan_daily_roll"),
        CheckConstraint("direction IN ('received', 'returned')", name="ck_fabric_scan_direction"),
        CheckConstraint("department IN ('CUT', 'ECT')", name="ck_fabric_scan_department"),
        CheckConstraint("roll_number > 0", name="ck_fabric_scan_roll"),
        Index("ix_fabric_scan_department_date", "department", "report_date"),
    )
    # Snapshot identifiers deliberately have no foreign keys or ORM cascades:
    # this register must not block or change inventory lifecycle operations.
    department: Mapped[str] = mapped_column(String(8), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False)
    roll_number: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    fabric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
