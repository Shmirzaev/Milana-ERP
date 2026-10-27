from __future__ import annotations
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class ForecastRecommendation(Base, PkMixin, TimestampMixin):
    __tablename__ = "forecast_recommendations"

    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    color: Mapped[str | None] = mapped_column(String(64))
    size: Mapped[str | None] = mapped_column(String(32))
    suggested_quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[str | None] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(Text)
    source_json: Mapped[dict | None] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
