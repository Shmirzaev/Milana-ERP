from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class PriceCalculationRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "price_calculation_requests"
    __table_args__ = (
        CheckConstraint("workflow_state IN ('legacy', 'collecting', 'awaiting_finance', 'approved', 'cancelled')", name="ck_price_workflow_state"),
        CheckConstraint("active_model_id IS NULL OR active_model_id = model_id", name="ck_price_active_variant"),
    )

    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False, index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    kroy_no: Mapped[str | None] = mapped_column(String(32), index=True)
    cutting_passport_id: Mapped[int | None] = mapped_column(ForeignKey("cutting_passports.id"))
    fabric_width_m: Mapped[float | None] = mapped_column(Numeric(14, 4))
    lay_length_m: Mapped[float | None] = mapped_column(Numeric(14, 4))
    size_count: Mapped[int | None] = mapped_column(Integer)
    gramage: Mapped[float | None] = mapped_column(Numeric(14, 6))
    binding_kg_per_piece: Mapped[float | None] = mapped_column(Numeric(14, 6))
    fabric_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    sewing_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    purchasing_updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    accessories_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    accessories_updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    cost_price_uzs: Mapped[float | None] = mapped_column(Numeric(18, 2))
    selling_price: Mapped[float | None] = mapped_column(Numeric(14, 4))
    profit_percentage: Mapped[float | None] = mapped_column(Numeric(8, 2))
    exchange_rate: Mapped[float | None] = mapped_column(Numeric(14, 4))
    finance_updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    # A nullable unique slot protects new requests without rewriting historical
    # duplicate rows. All writers acquire Model then PriceCalculationRequest.
    active_model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"), unique=True)
    workflow_state: Mapped[str] = mapped_column(String(32), nullable=False, default="legacy", server_default="legacy", index=True)
    factory_code: Mapped[str | None] = mapped_column(String(3), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    materials_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    passport_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    purchasing_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accessories_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    no_accessories_reason: Mapped[str | None] = mapped_column(Text)
    printing_cost: Mapped[float | None] = mapped_column(Numeric(14, 4))
    correction_team: Mapped[str | None] = mapped_column(String(16))
    correction_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approval_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    price_baseline_json: Mapped[dict | None] = mapped_column(JSON)

    # ``models`` also points back to the request that supplied its current price,
    # so this relationship must state which foreign key identifies the variant.
    model = relationship("Model", foreign_keys=[model_id], lazy="joined")
    cutting_passport = relationship("CuttingPassport", lazy="joined")
    approved_by = relationship("User", foreign_keys=[approved_by_id], lazy="joined")

