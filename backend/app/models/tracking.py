from __future__ import annotations
from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class Bundle(Base, PkMixin, TimestampMixin):
    __tablename__ = "bundles"
    bundle_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    qr_code_url: Mapped[str | None] = mapped_column(String(512))
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    current_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    next_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)

    scan_logs: Mapped[list["BundleScanLog"]] = relationship("BundleScanLog", back_populates="bundle", cascade="all, delete-orphan", order_by="BundleScanLog.scanned_at")


class BundleScanLog(Base, PkMixin):
    __tablename__ = "bundle_scan_logs"
    bundle_id: Mapped[int] = mapped_column(ForeignKey("bundles.id"), nullable=False)
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scan_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    to_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    location: Mapped[str | None] = mapped_column(String(128))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    bundle: Mapped["Bundle"] = relationship("Bundle", back_populates="scan_logs")


class Package(Base, PkMixin, TimestampMixin):
    __tablename__ = "packages"
    package_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    qr_code_url: Mapped[str | None] = mapped_column(String(512))
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    package_type: Mapped[str] = mapped_column(String(16), default="bag", nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    storage_cell: Mapped[str | None] = mapped_column(String(32))
    storage_shelf: Mapped[str | None] = mapped_column(String(8))
    storage_placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="packed", nullable=False)
    packed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["PackageItem"]] = relationship("PackageItem", back_populates="package", cascade="all, delete-orphan")
    scan_logs: Mapped[list["PackageScanLog"]] = relationship("PackageScanLog", back_populates="package", cascade="all, delete-orphan", order_by="PackageScanLog.scanned_at")


class PackageItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "package_items"
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="items")


class PackageScanLog(Base, PkMixin):
    __tablename__ = "package_scan_logs"
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scan_type: Mapped[str] = mapped_column(String(32), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="scan_logs")


class FinishedGoodsStock(Base, PkMixin, TimestampMixin):
    __tablename__ = "finished_goods_stock"
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sold_qty: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_per_piece: Mapped[float] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    selling_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(32), default="available", nullable=False)


class StockReservation(Base, PkMixin):
    __tablename__ = "stock_reservations"
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    finished_goods_stock_id: Mapped[int] = mapped_column(ForeignKey("finished_goods_stock.id"), nullable=False)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
