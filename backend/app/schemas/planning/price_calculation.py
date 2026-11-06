from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class PriceCalculationRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "price_calculation_requests"

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

    # ``models`` also points back to the request that supplied its current price,
    # so this relationship must state which foreign key identifies the variant.
    model = relationship("Model", foreign_keys=[model_id], lazy="joined")
    cutting_passport = relationship("CuttingPassport", lazy="joined")

