from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class Task(Base, PkMixin, TimestampMixin):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    # pending, in_progress, completed, cancelled
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    # low, medium, high, urgent
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
