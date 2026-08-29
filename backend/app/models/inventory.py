from __future__ import annotations
from datetime import datetime
from sqlalchemy import CheckConstraint, String, Integer, Boolean, ForeignKey, DateTime, Numeric, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class Item(Base, PkMixin, TimestampMixin):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint("default_cost >= 0", name="ck_items_default_cost_nonnegative"),
        CheckConstraint("reorder_level >= 0", name="ck_items_reorder_level_nonnegative"),
    )
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # fabric, accessory, semi_finished, finished, waste, packaging
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    default_cost: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    reorder_level: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    track_batch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512))
    composition_json: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)

    @property
    def composition(self) -> list[dict]:
        return self.composition_json or []


class Warehouse(Base, PkMixin, TimestampMixin):
    __tablename__ = "warehouses"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))


class StockBatch(Base, PkMixin, TimestampMixin):
    __tablename__ = "stock_batches"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_stock_batches_quantity_nonnegative"),
        CheckConstraint("cost_per_unit >= 0", name="ck_stock_batches_cost_nonnegative"),
        CheckConstraint("piece_count IS NULL OR piece_count >= 0", name="ck_stock_batches_piece_count_nonnegative"),
        CheckConstraint("qc_status IN ('pending', 'passed', 'failed', 'rejected', 'hold')", name="ck_stock_batches_qc_status"),
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    internal_batch_no: Mapped[str | None] = mapped_column(String(64), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    color: Mapped[str | None] = mapped_column(String(64))
    old_code: Mapped[str | None] = mapped_column(String(64))
    color_code: Mapped[str | None] = mapped_column(String(32))
    color_status: Mapped[str | None] = mapped_column(String(64))
    order_no: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[float | None] = mapped_column(Numeric(10, 2))
    gsm: Mapped[float | None] = mapped_column(Numeric(14, 6))
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    piece_count: Mapped[int | None] = mapped_column(Integer)
    roll_weights_kg: Mapped[list[float]] = mapped_column(JSON, default=list, nullable=False)
    processes: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_per_unit: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512))
    received_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    qc_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    item: Mapped["Item"] = relationship("Item", lazy="joined")


class StockMovement(Base, PkMixin):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_stock_movements_quantity_nonnegative"),
        CheckConstraint(
            "movement_type IN ('receive', 'transfer', 'issue', 'consume', 'adjustment', 'return', 'produce', 'waste', 'shipment')",
            name="ck_stock_movements_type",
        ),
    )
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


class MaterialReservation(Base, PkMixin, TimestampMixin):
    __tablename__ = "material_reservations"
    __table_args__ = (
        CheckConstraint("reserved_quantity > 0", name="ck_material_reservations_reserved_positive"),
        CheckConstraint("consumed_quantity >= 0", name="ck_material_reservations_consumed_nonnegative"),
        CheckConstraint("released_quantity >= 0", name="ck_material_reservations_released_nonnegative"),
        CheckConstraint(
            "consumed_quantity + released_quantity <= reserved_quantity",
            name="ck_material_reservations_consumed_released_lte_reserved",
        ),
        CheckConstraint(
            "status IN ('reserved', 'partially_consumed', 'consumed', 'released', 'cancelled')",
            name="ck_material_reservations_status",
        ),
        CheckConstraint(
            "reservation_type IN ('material', 'accessory', 'packaging')",
            name="ck_material_reservations_type",
        ),
        CheckConstraint(
            "source IN ('manual', 'auto_bom', 'planning')",
            name="ck_material_reservations_source",
        ),
    )

    reservation_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False, index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    stock_batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"), index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), index=True)
    reserved_quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    consumed_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    released_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="reserved", nullable=False, index=True)
    reservation_type: Mapped[str] = mapped_column(String(32), default="material", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    reserved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    item: Mapped["Item"] = relationship("Item", lazy="joined")
    stock_batch: Mapped["StockBatch | None"] = relationship("StockBatch", lazy="joined")
    warehouse: Mapped["Warehouse | None"] = relationship("Warehouse", lazy="joined")


class ManualAccessoryIssue(Base, PkMixin):
    __tablename__ = "manual_accessory_issues"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_manual_accessory_issues_quantity_positive"),
    )

    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False, index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), index=True)
    item_sku: Mapped[str | None] = mapped_column(String(64))
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    item: Mapped["Item | None"] = relationship("Item", lazy="joined")
