from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.production import WorkOrder


class SewingAssignment(Base, PkMixin, TimestampMixin):
    """Splits a sewing WorkOrder across one or more SewingFlows.

    A big order can run on Line 03 (300 pcs), Line 05 (300 pcs), Line 09 (400 pcs)
    in parallel. Each assignment has its own quantity, deadline, and status so
    planning can balance the load and supervisors see what their line owes.
    """
    __tablename__ = "sewing_assignments"

    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    sewing_flow_id: Mapped[int] = mapped_column(ForeignKey("sewing_flows.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="planned", nullable=False)
    # planned | in_progress | completed | cancelled | transferred
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    work_order: Mapped["WorkOrder"] = relationship("WorkOrder", back_populates="sewing_assignments")
