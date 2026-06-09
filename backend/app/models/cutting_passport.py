from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class CuttingPassport(Base, PkMixin, TimestampMixin):
    __tablename__ = "cutting_passports"

    passport_no: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Links to existing ERP data (optional)
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    # Identity fields (manual)
    variant: Mapped[str | None] = mapped_column(String(64))
    mold_no: Mapped[str | None] = mapped_column(String(64))        # Қолип рақам
    fabric_type: Mapped[str | None] = mapped_column(String(128))   # МАТО
    has_print: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # Печать
    lot_no: Mapped[str | None] = mapped_column(String(64))         # Партия рақам
    size_range: Mapped[str | None] = mapped_column(String(32))     # Размер e.g. "44-52"

    # Layup inputs (manual)
    rolls_count: Mapped[int | None] = mapped_column(Integer)       # Рулон сони
    layer_weight_kg: Mapped[float | None] = mapped_column(Numeric(14, 4))   # Бир қақат
    total_layers: Mapped[int | None] = mapped_column(Integer)      # Жами қават
    planned_kg: Mapped[float | None] = mapped_column(Numeric(14, 4))        # Кройга берилган КГ
    pieces: Mapped[int | None] = mapped_column(Integer)            # Иш сони
    fabric_width_m: Mapped[float | None] = mapped_column(Numeric(14, 4))    # Мато эни
    lay_length_m: Mapped[float | None] = mapped_column(Numeric(14, 4))      # Настил узунлиги
    gramage: Mapped[float | None] = mapped_column(Numeric(14, 6))  # Грамаж kg/m²
    waste_pct: Mapped[float | None] = mapped_column(Numeric(14, 4))         # Отход %

    # Accessory inputs (per piece, manual)
    beka_per_piece_kg: Mapped[float | None] = mapped_column(Numeric(14, 6))         # Битта ишга бейка
    other_beka_per_piece_kg: Mapped[float | None] = mapped_column(Numeric(14, 6))   # Битта ишга Бейка (other)
    scrap_kg: Mapped[float | None] = mapped_column(Numeric(14, 4))                  # Брак бичиш учун
    ribana_per_piece_kg: Mapped[float | None] = mapped_column(Numeric(14, 6))       # Битта ишга рибана

    notes: Mapped[str | None] = mapped_column(Text)

    production_order: Mapped["ProductionOrder | None"] = relationship(  # type: ignore[name-defined]
        "ProductionOrder", foreign_keys=[production_order_id], lazy="joined"
    )
    operator: Mapped["User | None"] = relationship(  # type: ignore[name-defined]
        "User", foreign_keys=[operator_id], lazy="joined"
    )
