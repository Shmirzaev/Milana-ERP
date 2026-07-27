from __future__ import annotations

from datetime import date

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class SewingDailyReport(Base, PkMixin, TimestampMixin):
    """Daily line output log.

    This is intentionally a reporting ledger only. Saving one of these rows
    does not update work order progress, bundle state, assignments, or payroll.
    """

    __tablename__ = "sewing_daily_reports"
    __table_args__ = (
        CheckConstraint("sewn_qty >= 0", name="ck_sewing_daily_reports_sewn_nonnegative"),
        CheckConstraint("defective_qty >= 0", name="ck_sewing_daily_reports_defective_nonnegative"),
        CheckConstraint("defective_qty <= sewn_qty", name="ck_sewing_daily_reports_defective_lte_sewn"),
    )

    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sewing_flow_id: Mapped[int] = mapped_column(ForeignKey("sewing_flows.id"), nullable=False, index=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), index=True)
    sewing_assignment_id: Mapped[int | None] = mapped_column(ForeignKey("sewing_assignments.id"), index=True)
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"), index=True)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)

    line_code: Mapped[str] = mapped_column(String(32), nullable=False)
    line_name: Mapped[str] = mapped_column(String(64), nullable=False)
    order_no: Mapped[str | None] = mapped_column(String(64))
    production_no: Mapped[str | None] = mapped_column(String(64))
    sales_order_no: Mapped[str | None] = mapped_column(String(64))
    manual_model_no: Mapped[str | None] = mapped_column(String(64))
    manual_variant_no: Mapped[str | None] = mapped_column(String(64))
    kroy_no: Mapped[str | None] = mapped_column(String(64))

    sewn_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    section_quantities: Mapped[list[int] | None] = mapped_column(JSON)
    section_no: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(64))
    top_qty: Mapped[int | None] = mapped_column(Integer)
    bottom_qty: Mapped[int | None] = mapped_column(Integer)
    defective_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
