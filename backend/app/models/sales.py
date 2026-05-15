from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class SalesOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "sales_orders"
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    order_type: Mapped[str] = mapped_column(String(32), default="client_order", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["SalesOrderItem"]] = relationship("SalesOrderItem", back_populates="sales_order", cascade="all, delete-orphan")


class SalesOrderItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "sales_order_items"
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
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
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    shipment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    packages: Mapped[list["ShipmentPackage"]] = relationship("ShipmentPackage", back_populates="shipment", cascade="all, delete-orphan")


class ShipmentPackage(Base, PkMixin, TimestampMixin):
    __tablename__ = "shipment_packages"
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), nullable=False)
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipment: Mapped["Shipment"] = relationship("Shipment", back_populates="packages")


class Invoice(Base, PkMixin, TimestampMixin):
    __tablename__ = "invoices"
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
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    external_source: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(32))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
