from __future__ import annotations
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class PurchaseRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "purchase_requests"

    request_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    sales_order = relationship("SalesOrder", lazy="joined")
    production_order = relationship("ProductionOrder", lazy="joined")
    lines: Mapped[list["PurchaseRequestLine"]] = relationship(
        "PurchaseRequestLine",
        back_populates="purchase_request",
        cascade="all, delete-orphan",
        order_by="PurchaseRequestLine.id",
    )

    @property
    def sales_order_no(self) -> str | None:
        return self.sales_order.order_no if self.sales_order else None

    @property
    def production_no(self) -> str | None:
        return self.production_order.production_no if self.production_order else None


class PurchaseRequestLine(Base, PkMixin, TimestampMixin):
    __tablename__ = "purchase_request_lines"

    purchase_request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    required_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    requested_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    available_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    shortage_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    preferred_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    material_name: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_request: Mapped["PurchaseRequest"] = relationship("PurchaseRequest", back_populates="lines")
    item = relationship("Item", lazy="joined")
    preferred_supplier = relationship("Supplier", lazy="joined")

    @property
    def item_sku(self) -> str | None:
        return self.item.sku if self.item else None

    @property
    def item_name(self) -> str | None:
        return self.item.name if self.item else None

    @property
    def preferred_supplier_name(self) -> str | None:
        return self.preferred_supplier.name if self.preferred_supplier else None


class PurchaseOrder(Base, PkMixin, TimestampMixin):
    __tablename__ = "purchase_orders"

    po_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    purchase_request_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_requests.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    ordered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    expected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_request = relationship("PurchaseRequest", lazy="joined")
    supplier = relationship("Supplier", lazy="joined")
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        "PurchaseOrderLine",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.id",
    )

    @property
    def request_no(self) -> str | None:
        return self.purchase_request.request_no if self.purchase_request else None

    @property
    def supplier_name(self) -> str | None:
        return self.supplier.name if self.supplier else None


class PurchaseOrderLine(Base, PkMixin, TimestampMixin):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    ordered_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    received_quantity: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    unit_cost: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    material_name: Mapped[str | None] = mapped_column(String(255))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)

    purchase_order: Mapped["PurchaseOrder"] = relationship("PurchaseOrder", back_populates="lines")
    item = relationship("Item", lazy="joined")
    warehouse = relationship("Warehouse", lazy="joined")
    supplier = relationship("Supplier", lazy="joined")

    @property
    def supplier_name(self) -> str | None:
        return self.supplier.name if self.supplier else None

    @property
    def item_sku(self) -> str | None:
        return self.item.sku if self.item else None

    @property
    def item_name(self) -> str | None:
        return self.item.name if self.item else None

    @property
    def warehouse_name(self) -> str | None:
        return self.warehouse.name if self.warehouse else None

    @property
    def remaining_quantity(self) -> float:
        return max(0.0, float(self.ordered_quantity or 0) - float(self.received_quantity or 0))
