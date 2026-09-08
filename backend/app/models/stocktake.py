from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin, TimestampMixin


class WarehouseStocktake(Base, PkMixin, TimestampMixin):
    __tablename__ = "warehouse_stocktakes"

    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WarehouseStocktakeRow(Base, PkMixin):
    __tablename__ = "warehouse_stocktake_rows"
    __table_args__ = (UniqueConstraint("stocktake_id", "identity", name="uq_stocktake_identity"),)

    stocktake_id: Mapped[int] = mapped_column(ForeignKey("warehouse_stocktakes.id"), index=True)
    identity: Mapped[str] = mapped_column(String(80), nullable=False)
    # Snapshot references deliberately survive later package deletion.
    package_id: Mapped[int | None] = mapped_column(Integer, index=True)
    expected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    final_snapshot: Mapped[dict | None] = mapped_column(JSON)
    scan_code: Mapped[str | None] = mapped_column(String(512))
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
