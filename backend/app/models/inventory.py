from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class Item(Base, PkMixin, TimestampMixin):
    __tablename__ = "items"
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # fabric, accessory, semi_finished, finished, waste, packaging
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    default_cost: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    reorder_level: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    track_batch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Warehouse(Base, PkMixin, TimestampMixin):
    __tablename__ = "warehouses"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))


class StockBatch(Base, PkMixin, TimestampMixin):
    __tablename__ = "stock_batches"
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    color: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[float | None] = mapped_column(Numeric(10, 2))
    gsm: Mapped[float | None] = mapped_column(Numeric(10, 2))
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_per_unit: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    received_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    qc_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)

    item: Mapped["Item"] = relationship("Item", lazy="joined")


class StockMovement(Base, PkMixin):
    __tablename__ = "stock_movements"
    movement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
