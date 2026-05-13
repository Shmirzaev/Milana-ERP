from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class ProductionOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_orders"
    production_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    production_type: Mapped[str] = mapped_column(String(32), nullable=False)  # client_order, branded_stock
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    destination_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["ProductionOrderItem"]] = relationship("ProductionOrderItem", back_populates="production_order", cascade="all, delete-orphan")
    work_orders: Mapped[list["WorkOrder"]] = relationship("WorkOrder", back_populates="production_order", cascade="all, delete-orphan")


class ProductionOrderItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_order_items"
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    production_order: Mapped["ProductionOrder"] = relationship("ProductionOrder", back_populates="items")


class WorkOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "work_orders"
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="waiting", nullable=False)
    planned_input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    planned_output_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_output_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sewing_flow_id: Mapped[int | None] = mapped_column(ForeignKey("sewing_flows.id"))
    # Block / pause flag so supervisors can flag a stuck job up the chain.
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    block_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    production_order: Mapped["ProductionOrder"] = relationship("ProductionOrder", back_populates="work_orders")
    sewing_assignments: Mapped[list["SewingAssignment"]] = relationship(
        "SewingAssignment", back_populates="work_order", cascade="all, delete-orphan",
    )


class CuttingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "cutting_records"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    fabric_batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    input_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    input_unit: Mapped[str] = mapped_column(String(32), default="meter", nullable=False)
    cut_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defective_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waste_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    waste_unit: Mapped[str] = mapped_column(String(32), default="kg", nullable=False)
    bundle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bundled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class PrintingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "printing_records"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    printed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    print_type: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class SewingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "sewing_records"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sewn_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    line_name: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class PackagingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "packaging_records"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    package_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_packed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packaging_material_used: Mapped[str | None] = mapped_column(String(255))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class QualityCheck(Base, PkMixin):
    __tablename__ = "quality_checks"
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    checked_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_type: Mapped[str | None] = mapped_column(String(128))
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    checked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
