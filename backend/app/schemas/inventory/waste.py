from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class WasteRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "waste_records"
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"))
    source_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    waste_type: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    sellable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    estimated_value: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="recorded", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class WasteSale(Base, PkMixin, TimestampMixin):
    __tablename__ = "waste_sales"
    waste_record_id: Mapped[int] = mapped_column(ForeignKey("waste_records.id"), nullable=False)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    sold_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WasteDisposalRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "waste_disposal_requests"
    waste_record_id: Mapped[int] = mapped_column(ForeignKey("waste_records.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proof_file_url: Mapped[str | None] = mapped_column(String(512))


def insert_waste_sale(
    db: Session, *, waste_record_id: int, buyer_name: str, quantity: Decimal,
    unit_price: Decimal, total_amount: Decimal, sold_by: int | None, sold_at: datetime,
) -> WasteSale:
    sale = WasteSale(
        waste_record_id=waste_record_id, buyer_name=buyer_name, quantity=quantity,
        unit_price=unit_price, total_amount=total_amount, sold_by=sold_by, sold_at=sold_at,
    )
    db.add(sale)
    db.flush()
    return sale


def set_waste_sale_status(record: WasteRecord, status: str) -> None:
    record.status = status
