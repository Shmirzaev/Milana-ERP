"""Physical manual receipt evidence and exact, persistent package print runs."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin


class ManualPackageReceipt(Base, PkMixin):
    __tablename__ = "manual_package_receipts"
    receipt_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class PackagePrintRun(Base, PkMixin):
    __tablename__ = "package_print_runs"
    run_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    packaging_department_code: Mapped[str] = mapped_column(String(16), nullable=False)
    package_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_location: Mapped[dict | None] = mapped_column(JSON)


class PackagePrintRunMember(Base, PkMixin):
    __tablename__ = "package_print_run_members"
    __table_args__ = (UniqueConstraint("package_id", name="uq_package_print_run_member_package"),)
    run_id: Mapped[int] = mapped_column(ForeignKey("package_print_runs.id"), index=True, nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
