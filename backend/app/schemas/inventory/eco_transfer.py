"""Internal custody ledger. No Eco Cotton inventory or production rows are created."""
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, Numeric, JSON, CheckConstraint, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, PkMixin


class EcoFabricDispatch(Base, PkMixin):
    __tablename__ = "eco_fabric_dispatches"
    request_key: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(128), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    remaining_inventory: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class EcoFabricRoll(Base, PkMixin):
    __tablename__ = "eco_fabric_rolls"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND roll_number > 0", name="ck_eco_fabric_roll_positive"),
        Index("uq_eco_fabric_roll_out", "batch_id", "roll_number", unique=True,
              postgresql_where=text("returned_at IS NULL"),
              sqlite_where=text("returned_at IS NULL")),
    )
    dispatch_id: Mapped[int] = mapped_column(ForeignKey("eco_fabric_dispatches.id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), nullable=False, index=True)
    roll_number: Mapped[int] = mapped_column(Integer, nullable=False)
    fabric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    return_operator_name: Mapped[str | None] = mapped_column(String(128))
    return_key: Mapped[str | None] = mapped_column(String(36), unique=True)
