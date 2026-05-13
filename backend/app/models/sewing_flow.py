from __future__ import annotations
from sqlalchemy import String, Integer, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class SewingFlow(Base, PkMixin, TimestampMixin):
    """A physical sewing line / flow. The factory has 30 of these.

    Planning assigns sewing work orders to a specific flow so each line knows
    what to sew next and Management can see the workload per line.
    """
    __tablename__ = "sewing_flows"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    capacity_per_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
