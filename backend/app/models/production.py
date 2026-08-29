from __future__ import annotations
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import CheckConstraint, String, Integer, Boolean, ForeignKey, DateTime, Text, Numeric, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.partners import Customer
    from app.models.sales import SalesOrder
    from app.models.sewing_assignment import SewingAssignment


def public_production_order_no(production_no: str | None) -> str | None:
    text = str(production_no or "").strip()
    if not text:
        return None
    if text.upper().startswith("PO-"):
        return f"SO-{text[3:]}"
    return text


class BrandedPlanningOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "branded_planning_orders"
    __table_args__ = (
        CheckConstraint(
            "ordered_for_type IN ('customer', 'milana', 'eco_cotton', 'besttex')",
            name="ck_branded_planning_orders_ordered_for_type",
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'cancelled')",
            name="ck_branded_planning_orders_status",
        ),
    )
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    ordered_for_type: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    ordered_for_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    customer: Mapped["Customer | None"] = relationship("Customer")
    production_orders: Mapped[list["ProductionOrder"]] = relationship(
        "ProductionOrder", back_populates="planning_order",
    )


class ProductionOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_orders"
    __table_args__ = (
        CheckConstraint("planned_quantity >= 0", name="ck_production_orders_planned_quantity_nonnegative"),
        CheckConstraint("source_type IN ('standard', 'usluga')", name="ck_production_orders_source_type"),
        CheckConstraint(
            "service_material_usage_kg IS NULL OR service_material_usage_kg >= 0",
            name="ck_production_orders_service_material_usage_nonnegative",
        ),
    )
    production_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    production_type: Mapped[str] = mapped_column(String(32), nullable=False)  # client_order, branded_stock
    source_type: Mapped[str] = mapped_column(String(16), nullable=False, default="standard", server_default="standard", index=True)
    planning_order_id: Mapped[int | None] = mapped_column(ForeignKey("branded_planning_orders.id"), index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), index=True)
    fabric_batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_material_code: Mapped[str | None] = mapped_column(String(128))
    estimated_material_amount: Mapped[float | None] = mapped_column(Numeric(14, 4))
    estimated_material_unit: Mapped[str | None] = mapped_column(String(32))
    printing_instructions: Mapped[str | None] = mapped_column(Text)
    printing_attachments: Mapped[list[dict] | None] = mapped_column(JSON, default=list)
    destination_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    service_customer_name: Mapped[str | None] = mapped_column(String(255))
    service_customer_reference: Mapped[str | None] = mapped_column(String(128))
    service_material_description: Mapped[str | None] = mapped_column(Text)
    service_material_usage_kg: Mapped[float | None] = mapped_column(Numeric(14, 4))
    service_material_notes: Mapped[str | None] = mapped_column(Text)
    service_handover_recipient: Mapped[str | None] = mapped_column(String(255))
    service_handover_notes: Mapped[str | None] = mapped_column(Text)
    handed_over_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handed_over_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    sales_order: Mapped["SalesOrder | None"] = relationship("SalesOrder")
    planning_order: Mapped["BrandedPlanningOrder | None"] = relationship(
        "BrandedPlanningOrder", back_populates="production_orders",
    )
    materials: Mapped[list["ProductionOrderMaterial"]] = relationship(
        "ProductionOrderMaterial",
        back_populates="production_order",
        cascade="all, delete-orphan",
        order_by="ProductionOrderMaterial.position",
        lazy="selectin",
    )
    batches: Mapped[list["ProductionBatch"]] = relationship("ProductionBatch", back_populates="production_order", cascade="all, delete-orphan")
    items: Mapped[list["ProductionOrderItem"]] = relationship("ProductionOrderItem", back_populates="production_order", cascade="all, delete-orphan")
    work_orders: Mapped[list["WorkOrder"]] = relationship("WorkOrder", back_populates="production_order", cascade="all, delete-orphan")

    @property
    def sales_order_no(self) -> str | None:
        return self.sales_order.order_no if self.sales_order else None

    @property
    def order_no(self) -> str:
        return self.sales_order_no or public_production_order_no(self.production_no) or self.production_no


class ProductionOrderMaterial(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_order_materials"
    __table_args__ = (
        CheckConstraint("estimated_quantity > 0", name="ck_production_order_materials_quantity_positive"),
        CheckConstraint("position > 0", name="ck_production_order_materials_position_positive"),
        UniqueConstraint(
            "production_order_id", "stock_batch_id",
            name="uq_production_order_materials_order_batch",
        ),
        UniqueConstraint(
            "production_order_id", "position",
            name="uq_production_order_materials_order_position",
        ),
    )
    production_order_id: Mapped[int] = mapped_column(
        ForeignKey("production_orders.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    stock_batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), nullable=False, index=True)
    estimated_quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    production_order: Mapped["ProductionOrder"] = relationship(
        "ProductionOrder", back_populates="materials",
    )
    stock_batch = relationship("StockBatch")


class ProductionBatch(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_batches"
    __table_args__ = (
        CheckConstraint("batch_index > 0", name="ck_production_batches_index_positive"),
        CheckConstraint("planned_quantity >= 0", name="ck_production_batches_planned_quantity_nonnegative"),
        UniqueConstraint("production_order_id", "batch_no", name="uq_production_batches_order_batch_no"),
    )
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False, index=True)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    production_order: Mapped["ProductionOrder"] = relationship("ProductionOrder", back_populates="batches")
    work_orders: Mapped[list["WorkOrder"]] = relationship("WorkOrder", back_populates="production_batch")


class ProductionOrderItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "production_order_items"
    __table_args__ = (
        CheckConstraint("planned_quantity >= 0", name="ck_production_order_items_planned_nonnegative"),
        CheckConstraint("completed_quantity >= 0", name="ck_production_order_items_completed_nonnegative"),
    )
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    printing_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    production_order: Mapped["ProductionOrder"] = relationship("ProductionOrder", back_populates="items")


class WorkOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint("planned_input_qty >= 0", name="ck_work_orders_planned_input_nonnegative"),
        CheckConstraint("planned_output_qty >= 0", name="ck_work_orders_planned_output_nonnegative"),
        CheckConstraint("actual_input_qty >= 0", name="ck_work_orders_actual_input_nonnegative"),
        CheckConstraint("actual_output_qty >= 0", name="ck_work_orders_actual_output_nonnegative"),
        CheckConstraint("passed_qty >= 0", name="ck_work_orders_passed_nonnegative"),
        CheckConstraint("failed_qty >= 0", name="ck_work_orders_failed_nonnegative"),
        CheckConstraint("rework_qty >= 0", name="ck_work_orders_rework_nonnegative"),
        CheckConstraint(
            "status IN ('new', 'planning', 'waiting', 'pending', 'ready', 'collected', 'in_progress', 'paused', "
            "'completed', 'rejected', 'cancelled')",
            name="ck_work_orders_status",
        ),
        UniqueConstraint("production_order_id", "production_batch_id", "operation", name="uq_work_orders_order_batch_operation"),
    )
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
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
    production_batch: Mapped[ProductionBatch | None] = relationship("ProductionBatch", back_populates="work_orders")
    sewing_assignments: Mapped[list["SewingAssignment"]] = relationship(
        "SewingAssignment", back_populates="work_order", cascade="all, delete-orphan",
    )

    @property
    def production_no(self) -> str | None:
        return self.production_order.production_no if self.production_order else None

    @property
    def sales_order_no(self) -> str | None:
        return self.production_order.sales_order_no if self.production_order else None

    @property
    def order_no(self) -> str | None:
        return self.production_order.order_no if self.production_order else self.production_no


class CuttingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "cutting_records"
    __table_args__ = (
        CheckConstraint("input_quantity >= 0", name="ck_cutting_records_input_nonnegative"),
        CheckConstraint("cut_pieces >= 0", name="ck_cutting_records_cut_nonnegative"),
        CheckConstraint("report_piece_count >= 0", name="ck_cutting_records_report_piece_nonnegative"),
        CheckConstraint("passed_pieces >= 0", name="ck_cutting_records_passed_nonnegative"),
        CheckConstraint("defective_pieces >= 0", name="ck_cutting_records_defective_nonnegative"),
        CheckConstraint("waste_quantity >= 0", name="ck_cutting_records_waste_nonnegative"),
        CheckConstraint("layer_material_kg >= 0", name="ck_cutting_records_layer_material_nonnegative"),
        CheckConstraint("beika_kg >= 0", name="ck_cutting_records_beika_nonnegative"),
        CheckConstraint("material_rolls_used >= 0", name="ck_cutting_records_rolls_nonnegative"),
        CheckConstraint("bundle_count >= 0", name="ck_cutting_records_bundle_count_nonnegative"),
        CheckConstraint("total_bundled_quantity >= 0", name="ck_cutting_records_total_bundled_nonnegative"),
        CheckConstraint(
            "material_role IS NULL OR material_role IN ('main', 'secondary')",
            name="ck_cutting_records_material_role",
        ),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_cutting_records_approval_status",
        ),
    )
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
    fabric_batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    model_bom_id: Mapped[int | None] = mapped_column(ForeignKey("model_bom.id"), index=True)
    cutting_batch_no: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    material_name_snapshot: Mapped[str | None] = mapped_column(String(255))
    material_role: Mapped[str | None] = mapped_column(String(16))
    approval_status: Mapped[str] = mapped_column(String(16), default="approved", nullable=False, index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    input_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    input_unit: Mapped[str] = mapped_column(String(32), default="kg", nullable=False)
    cut_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_piece_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defective_pieces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waste_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    waste_unit: Mapped[str] = mapped_column(String(32), default="kg", nullable=False)
    layer_material_kg: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    beika_kg: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    material_rolls_used: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    bundle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_bundled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    layup_operator_name: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
    materials: Mapped[list["CuttingMaterialUsage"]] = relationship(
        "CuttingMaterialUsage",
        back_populates="cutting_record",
        cascade="all, delete-orphan",
        order_by="CuttingMaterialUsage.position",
        lazy="selectin",
    )


class CuttingMaterialUsage(Base, PkMixin, TimestampMixin):
    __tablename__ = "cutting_material_usages"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cutting_material_usages_quantity_positive"),
        CheckConstraint("position > 0", name="ck_cutting_material_usages_position_positive"),
        UniqueConstraint(
            "cutting_record_id", "stock_batch_id",
            name="uq_cutting_material_usages_record_batch",
        ),
        UniqueConstraint(
            "cutting_record_id", "position",
            name="uq_cutting_material_usages_record_position",
        ),
    )
    cutting_record_id: Mapped[int] = mapped_column(
        ForeignKey("cutting_records.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    stock_batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    cutting_record: Mapped["CuttingRecord"] = relationship(
        "CuttingRecord", back_populates="materials",
    )
    stock_batch = relationship("StockBatch")


class PrintingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "printing_records"
    __table_args__ = (
        CheckConstraint("input_qty >= 0", name="ck_printing_records_input_nonnegative"),
        CheckConstraint("printed_qty >= 0", name="ck_printing_records_printed_nonnegative"),
        CheckConstraint("passed_qty >= 0", name="ck_printing_records_passed_nonnegative"),
        CheckConstraint("rejected_qty >= 0", name="ck_printing_records_rejected_nonnegative"),
    )
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
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
    __table_args__ = (
        CheckConstraint("input_qty >= 0", name="ck_sewing_records_input_nonnegative"),
        CheckConstraint("sewn_qty >= 0", name="ck_sewing_records_sewn_nonnegative"),
        CheckConstraint("passed_qty >= 0", name="ck_sewing_records_passed_nonnegative"),
        CheckConstraint("failed_qty >= 0", name="ck_sewing_records_failed_nonnegative"),
        CheckConstraint("rework_qty >= 0", name="ck_sewing_records_rework_nonnegative"),
        CheckConstraint("rejected_qty >= 0", name="ck_sewing_records_rejected_nonnegative"),
    )
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
    input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sewn_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rework_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_quantities: Mapped[list[dict] | None] = mapped_column(JSON, default=list)
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    line_name: Mapped[str | None] = mapped_column(String(64))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class SewingReplacementRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "sewing_replacement_requests"
    __table_args__ = (
        CheckConstraint("requested_qty > 0", name="ck_sewing_replacements_requested_positive"),
        CheckConstraint("cut_qty >= 0", name="ck_sewing_replacements_cut_nonnegative"),
        CheckConstraint("replaced_qty >= 0", name="ck_sewing_replacements_replaced_nonnegative"),
        CheckConstraint("cut_qty <= requested_qty", name="ck_sewing_replacements_cut_lte_requested"),
        CheckConstraint("replaced_qty <= requested_qty", name="ck_sewing_replacements_replaced_lte_requested"),
        CheckConstraint(
            "status IN ('waiting_cutting', 'waiting_sewing', 'completed')",
            name="ck_sewing_replacements_status",
        ),
        UniqueConstraint("sewing_record_id", name="uq_sewing_replacements_sewing_record"),
    )
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False, index=True)
    sewing_work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    cutting_work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), index=True)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    sewing_record_id: Mapped[int] = mapped_column(ForeignKey("sewing_records.id"), nullable=False)
    requested_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    cut_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replaced_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="waiting_cutting", nullable=False, index=True)
    defect_reason: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class PackagingRecord(Base, PkMixin, TimestampMixin):
    __tablename__ = "packaging_records"
    __table_args__ = (
        CheckConstraint("input_qty >= 0", name="ck_packaging_records_input_nonnegative"),
        CheckConstraint("packed_qty >= 0", name="ck_packaging_records_packed_nonnegative"),
        CheckConstraint("damaged_qty >= 0", name="ck_packaging_records_damaged_nonnegative"),
        CheckConstraint("package_count >= 0", name="ck_packaging_records_package_count_nonnegative"),
        CheckConstraint("total_packed_quantity >= 0", name="ck_packaging_records_total_packed_nonnegative"),
    )
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"))
    input_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packed_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    damaged_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    package_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_packed_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    packaging_material_used: Mapped[str | None] = mapped_column(String(255))
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class PackagingReceipt(Base, PkMixin, TimestampMixin):
    __tablename__ = "packaging_receipts"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_packaging_receipts_quantity_positive"),
        CheckConstraint("receive_method IN ('scan', 'manual')", name="ck_packaging_receipts_method"),
        CheckConstraint(
            "packaging_department_code IN ('PKG', 'BPK', 'ECP')",
            name="ck_packaging_receipts_department",
        ),
        UniqueConstraint("bundle_id", name="uq_packaging_receipts_bundle"),
    )
    packaging_department_code: Mapped[str] = mapped_column(String(16), default="PKG", nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    source_work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False, index=True)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    bundle_id: Mapped[int | None] = mapped_column(ForeignKey("bundles.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    receive_method: Mapped[str] = mapped_column(String(16), nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class QualityCheck(Base, PkMixin):
    __tablename__ = "quality_checks"
    __table_args__ = (
        CheckConstraint("checked_qty >= 0", name="ck_quality_checks_checked_nonnegative"),
        CheckConstraint("passed_qty >= 0", name="ck_quality_checks_passed_nonnegative"),
        CheckConstraint("failed_qty >= 0", name="ck_quality_checks_failed_nonnegative"),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_quality_checks_severity"),
    )
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
