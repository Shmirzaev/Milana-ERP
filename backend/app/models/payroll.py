from __future__ import annotations
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class PayrollPeriod(Base, PkMixin, TimestampMixin):
    __tablename__ = "payroll_periods"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'open', 'locked', 'approved', 'paid', 'cancelled')",
            name="ck_payroll_periods_status",
        ),
        CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_payroll_periods_factory_code"),
        UniqueConstraint("factory_code", "period_no", name="uq_payroll_periods_factory_period_no"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, default="MIL", server_default="MIL", index=True)
    period_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    records: Mapped[list["PayrollRecord"]] = relationship("PayrollRecord", back_populates="period")


class PayrollRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "payroll_records"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_payroll_records_quantity_nonnegative"),
        CheckConstraint("rate_per_piece >= 0", name="ck_payroll_records_rate_nonnegative"),
        CheckConstraint("total_amount >= 0", name="ck_payroll_records_total_nonnegative"),
        CheckConstraint(
            "status IN ('recorded', 'voided', 'approved', 'paid')",
            name="ck_payroll_records_status",
        ),
        CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_payroll_records_factory_code"),
        UniqueConstraint("factory_code", "scan_uid", name="uq_payroll_records_factory_scan_uid"),
        UniqueConstraint("factory_code", "dedupe_key", name="uq_payroll_records_factory_dedupe_key"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, default="MIL", server_default="MIL", index=True)
    payroll_period_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_periods.id"), index=True)
    scan_uid: Mapped[str | None] = mapped_column(String(128), index=True)
    original_scan_uid: Mapped[str | None] = mapped_column(String(128), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    employee_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"))
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))

    production_no: Mapped[str | None] = mapped_column(String(64))
    sales_order_no: Mapped[str | None] = mapped_column(String(64))
    batch_no: Mapped[str | None] = mapped_column(String(64))
    model_code: Mapped[str | None] = mapped_column(String(64))
    operation_section: Mapped[str | None] = mapped_column(String(64))
    operation_code: Mapped[str | None] = mapped_column(String(64))
    operation_name: Mapped[str | None] = mapped_column(String(255))

    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    rate_per_piece: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="UZS", nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="payroll_scan", nullable=False)
    raw_employee_json: Mapped[dict | None] = mapped_column(JSON)
    raw_work_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="recorded", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    period: Mapped[PayrollPeriod | None] = relationship("PayrollPeriod", back_populates="records")


class PayrollQrLabel(Base, PkMixin, TimestampMixin):
    __tablename__ = "payroll_qr_labels"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_payroll_qr_labels_quantity_nonnegative"),
        CheckConstraint("rate_per_piece >= 0", name="ck_payroll_qr_labels_rate_nonnegative"),
        CheckConstraint("return_count >= 0", name="ck_payroll_qr_labels_return_count_nonnegative"),
        CheckConstraint("status IN ('available', 'scanned', 'superseded')", name="ck_payroll_qr_labels_status"),
        CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_payroll_qr_labels_factory_code"),
        UniqueConstraint("factory_code", "label_uid", name="uq_payroll_qr_labels_factory_label_uid"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, default="MIL", server_default="MIL", index=True)
    label_uid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[str | None] = mapped_column(Text)
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"), index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), index=True)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    production_no: Mapped[str | None] = mapped_column(String(64))
    sales_order_no: Mapped[str | None] = mapped_column(String(64), index=True)
    batch_no: Mapped[str | None] = mapped_column(String(64))
    model_code: Mapped[str | None] = mapped_column(String(64))
    operation_section: Mapped[str | None] = mapped_column(String(64))
    operation_code: Mapped[str | None] = mapped_column(String(64))
    operation_name: Mapped[str | None] = mapped_column(String(255))
    sewing_flow_id: Mapped[int | None] = mapped_column(ForeignKey("sewing_flows.id", ondelete="SET NULL"), index=True)
    sewing_line_code: Mapped[str | None] = mapped_column(String(64))
    sewing_line_name: Mapped[str | None] = mapped_column(String(255))
    cutting_passport_id: Mapped[int | None] = mapped_column(ForeignKey("cutting_passports.id", ondelete="SET NULL"), index=True)
    cutting_passport_no: Mapped[str | None] = mapped_column(String(64), index=True)
    size: Mapped[str | None] = mapped_column(String(32))
    copy_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    rate_per_piece: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="UZS", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="available", nullable=False, index=True)
    payroll_record_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_records.id"), index=True)
    issued_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    return_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    split_from_label_id: Mapped[int | None] = mapped_column(
        ForeignKey("payroll_qr_labels.id", ondelete="RESTRICT"),
        index=True,
    )


class PayrollAdjustment(Base, PkMixin):
    __tablename__ = "payroll_adjustments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payroll_adjustments_amount_nonnegative"),
        CheckConstraint("adjustment_type IN ('bonus', 'deduction')", name="ck_payroll_adjustments_type"),
        CheckConstraint("factory_code IN ('MIL', 'BST', 'ECO')", name="ck_payroll_adjustments_factory_code"),
        UniqueConstraint("source_payroll_record_id", name="uq_payroll_adjustments_source_record"),
    )

    factory_code: Mapped[str] = mapped_column(String(3), nullable=False, default="MIL", server_default="MIL", index=True)
    payroll_period_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_periods.id"), index=True)
    source_payroll_record_id: Mapped[int | None] = mapped_column(ForeignKey("payroll_records.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    adjustment_type: Mapped[str] = mapped_column(String(16), default="bonus", nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="UZS", nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    @property
    def signed_amount(self) -> Decimal:
        amount = self.amount or Decimal("0")
        return -amount if self.adjustment_type == "deduction" else amount
