from __future__ import annotations
from datetime import datetime
from sqlalchemy import CheckConstraint, String, Integer, Boolean, ForeignKey, DateTime, Text, Numeric, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class SalesOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_sales_orders_total_nonnegative"),
        CheckConstraint(
            "status IN ('draft', 'pending_sales_approval', 'confirmed', 'planning', 'planning_approved', "
            "'in_production', 'production', 'cutting', 'printing', 'sewing', 'packaging', 'storage', "
            "'ready_to_ship', 'ready', 'reserved', 'shipped', 'delivered', 'closed', 'cancelled')",
            name="ck_sales_orders_status",
        ),
    )
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    order_type: Mapped[str] = mapped_column(String(32), default="client_order", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    planning_estimated_material_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_estimated_labor_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_estimated_electricity_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_estimated_other_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_estimated_net_cost: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_suggested_price_15: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_suggested_price_20: Mapped[float | None] = mapped_column(Numeric(14, 2))
    planning_estimated_lead_time_minutes: Mapped[int | None] = mapped_column(Integer)
    planning_estimate_comment: Mapped[str | None] = mapped_column(Text)
    planning_estimate_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planning_estimate_submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    printing_instructions: Mapped[str | None] = mapped_column(Text)
    printing_attachments: Mapped[list[dict] | None] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["SalesOrderItem"]] = relationship("SalesOrderItem", back_populates="sales_order", cascade="all, delete-orphan")


class SalesOrderItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_sales_order_items_quantity_nonnegative"),
        CheckConstraint("unit_price >= 0", name="ck_sales_order_items_unit_price_nonnegative"),
        CheckConstraint(
            "model_id IS NOT NULL OR finished_goods_stock_id IS NOT NULL",
            name="ck_sales_order_items_product_reference",
        ),
    )
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"))
    finished_goods_stock_id: Mapped[int | None] = mapped_column(
        ForeignKey("finished_goods_stock.id"), index=True
    )
    source_model_code: Mapped[str | None] = mapped_column(String(64))
    source_model_name: Mapped[str | None] = mapped_column(String(255))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    printing_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="produce_new", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    sales_order: Mapped["SalesOrder"] = relationship("SalesOrder", back_populates="items")


class Shipment(Base, PkMixin, TimestampMixin):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'created', 'shipped', 'delivered', 'cancelled')", name="ck_shipments_status"),
    )
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    shipment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    packages: Mapped[list["ShipmentPackage"]] = relationship("ShipmentPackage", back_populates="shipment", cascade="all, delete-orphan")
    scan_logs: Mapped[list["ShipmentScanLog"]] = relationship(
        "ShipmentScanLog",
        back_populates="shipment",
        cascade="all, delete-orphan",
        order_by="ShipmentScanLog.scanned_at",
    )


class ShipmentPackage(Base, PkMixin, TimestampMixin):
    __tablename__ = "shipment_packages"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_shipment_packages_quantity_positive"),
        UniqueConstraint("shipment_id", "package_id", name="uq_shipment_packages_shipment_package"),
    )
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="packages")


class ShipmentScanLog(Base, PkMixin):
    __tablename__ = "shipment_scan_logs"
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"), index=True)
    scanned_code: Mapped[str] = mapped_column(String(128), nullable=False)
    scan_result: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="scan_logs")


class Invoice(Base, PkMixin, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_invoices_amount_nonnegative"),
        CheckConstraint("status IN ('unpaid', 'partially_paid', 'paid', 'void', 'cancelled')", name="ck_invoices_status"),
    )
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    invoice_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    external_source: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unpaid", nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base, PkMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    external_source: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(32))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
