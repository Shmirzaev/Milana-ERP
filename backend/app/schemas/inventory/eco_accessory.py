"""ECO order-level approvals and the stock batches they allocate."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, PkMixin, TimestampMixin
from app.libs.enums.eco_accessories import EcoAccessoryStatus


class EcoAccessoryPlan(Base, PkMixin, TimestampMixin):
    __tablename__ = "eco_accessory_plans"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(repr(s.value) for s in EcoAccessoryStatus) + ")", name="ck_eco_accessory_plan_status"),
        CheckConstraint("revision > 0 AND planned_quantity >= 0", name="ck_eco_accessory_plan_revision"),
    )
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), unique=True, nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    planning_order_id: Mapped[int] = mapped_column(ForeignKey("branded_planning_orders.id"), nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=EcoAccessoryStatus.DRAFT.value, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    approval_notes: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class EcoAccessoryRequirement(Base, PkMixin):
    __tablename__ = "eco_accessory_requirements"
    __table_args__ = (UniqueConstraint("plan_id", "item_id"), CheckConstraint("quantity > 0", name="ck_eco_accessory_req_qty"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("eco_accessory_plans.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)


class EcoAccessoryAllocation(Base, PkMixin):
    __tablename__ = "eco_accessory_allocations"
    __table_args__ = (
        UniqueConstraint("requirement_id", "batch_id"),
        CheckConstraint("quantity > 0 AND issued_quantity >= 0 AND issued_quantity <= quantity", name="ck_eco_accessory_allocation_qty"),
    )
    requirement_id: Mapped[int] = mapped_column(ForeignKey("eco_accessory_requirements.id"), nullable=False, index=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("eco_material_batches.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    issued_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
