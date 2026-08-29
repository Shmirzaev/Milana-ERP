from __future__ import annotations
from datetime import datetime
from sqlalchemy import CheckConstraint, String, Integer, ForeignKey, DateTime, Text, Numeric, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PkMixin, TimestampMixin


class Bundle(Base, PkMixin, TimestampMixin):
    __tablename__ = "bundles"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_bundles_quantity_positive"),
        CheckConstraint(
            "status IN ('created', 'sent_to_printing', 'received_printing', 'sent_to_sewing', 'received_sewing', 'cancelled')",
            name="ck_bundles_status",
        ),
    )
    bundle_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    qr_code_url: Mapped[str | None] = mapped_column(String(512))
    production_order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id"), nullable=False)
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    cutting_record_id: Mapped[int | None] = mapped_column(ForeignKey("cutting_records.id"), index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    current_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    next_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    sewing_factory_code: Mapped[str | None] = mapped_column(String(32))
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
    __table_args__ = (
        CheckConstraint("total_quantity >= 0", name="ck_packages_total_quantity_nonnegative"),
        CheckConstraint("capacity > 0", name="ck_packages_capacity_positive"),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="ck_packages_weight_nonnegative"),
        CheckConstraint(
            "packaging_department_code IN ('PKG', 'BPK', 'ECP')",
            name="ck_packages_packaging_department",
        ),
        CheckConstraint(
            "status IN ('packed', 'handed_over', 'received_in_storage', 'reserved', 'shipped', 'delivered', 'damaged')",
            name="ck_packages_status",
        ),
        CheckConstraint(
            "production_order_id IS NOT NULL OR legacy_receipt_id IS NOT NULL",
            name="ck_packages_source_evidence",
        ),
    )
    package_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    barcode: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    packaging_department_code: Mapped[str] = mapped_column(String(16), default="PKG", nullable=False, index=True)
    qr_code_url: Mapped[str | None] = mapped_column(String(512))
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"))
    legacy_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("legacy_stock_receipts.id"), unique=True, index=True
    )
    production_batch_id: Mapped[int | None] = mapped_column(ForeignKey("production_batches.id"), index=True)
    sales_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id"))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    package_type: Mapped[str] = mapped_column(String(16), default="bag", nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(14, 4))
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
    batch_allocations: Mapped[list["PackageBatchAllocation"]] = relationship("PackageBatchAllocation", back_populates="package", cascade="all, delete-orphan")
    scan_logs: Mapped[list["PackageScanLog"]] = relationship("PackageScanLog", back_populates="package", cascade="all, delete-orphan", order_by="PackageScanLog.scanned_at")
    barcode_aliases: Mapped[list["PackageBarcodeAlias"]] = relationship(
        "PackageBarcodeAlias", back_populates="package", cascade="all, delete-orphan"
    )
    legacy_receipt: Mapped["LegacyStockReceipt | None"] = relationship(
        "LegacyStockReceipt", back_populates="package"
    )


class LegacyStockReceipt(Base, PkMixin, TimestampMixin):
    """Immutable source evidence for stock migrated from a legacy ERP."""

    __tablename__ = "legacy_stock_receipts"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_warehouse_id",
            "source_record_id",
            name="uq_legacy_stock_receipts_source_record",
        ),
    )

    source_system: Mapped[str] = mapped_column(String(32), nullable=False, default="UZERP")
    source_warehouse_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_warehouse_name: Mapped[str | None] = mapped_column(String(255))
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    imported_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    package: Mapped["Package | None"] = relationship(
        "Package", back_populates="legacy_receipt", uselist=False
    )


class PackageBarcodeAlias(Base, PkMixin, TimestampMixin):
    """A scannable legacy code attached to a package.

    Legacy codes are intentionally not globally unique; old ERP reports reuse
    some product and sewing codes across multiple physical stock rows.
    """

    __tablename__ = "package_barcode_aliases"
    __table_args__ = (
        UniqueConstraint("package_id", "code", name="uq_package_barcode_alias_package_code"),
    )

    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    code_type: Mapped[str] = mapped_column(String(32), nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="barcode_aliases")


class PackageItem(Base, PkMixin, TimestampMixin):
    __tablename__ = "package_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_package_items_quantity_positive"),
    )
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    color: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="items")


class PackageBatchAllocation(Base, PkMixin, TimestampMixin):
    __tablename__ = "package_batch_allocations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_package_batch_allocations_quantity_positive"),
        UniqueConstraint("package_id", "production_batch_id", name="uq_package_batch_allocations_package_batch"),
    )
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False, index=True)
    production_batch_id: Mapped[int] = mapped_column(ForeignKey("production_batches.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="batch_allocations")


class PackageScanLog(Base, PkMixin):
    __tablename__ = "package_scan_logs"
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), nullable=False)
    scanned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scan_type: Mapped[str] = mapped_column(String(32), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    package: Mapped["Package"] = relationship("Package", back_populates="scan_logs")


class PackageChangeRequest(Base, PkMixin, TimestampMixin):
    __tablename__ = "package_change_requests"
    __table_args__ = (
        CheckConstraint("request_type IN ('edit', 'delete')", name="ck_package_change_requests_type"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_package_change_requests_status"),
    )
    package_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    package_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)  # edit, delete
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False, index=True)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_notes: Mapped[str | None] = mapped_column(Text)


class FinishedGoodsStock(Base, PkMixin, TimestampMixin):
    __tablename__ = "finished_goods_stock"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_finished_goods_quantity_nonnegative"),
        CheckConstraint("available_qty >= 0", name="ck_finished_goods_available_nonnegative"),
        CheckConstraint("reserved_qty >= 0", name="ck_finished_goods_reserved_nonnegative"),
        CheckConstraint("sold_qty >= 0", name="ck_finished_goods_sold_nonnegative"),
        CheckConstraint("cost_per_piece >= 0", name="ck_finished_goods_cost_nonnegative"),
        CheckConstraint("selling_price >= 0", name="ck_finished_goods_price_nonnegative"),
        CheckConstraint("status IN ('available', 'reserved', 'sold', 'damaged')", name="ck_finished_goods_status"),
    )
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
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_reservations_quantity_positive"),
        UniqueConstraint("sales_order_id", "finished_goods_stock_id", "package_id", name="uq_stock_reservations_order_stock_package"),
    )
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), nullable=False)
    finished_goods_stock_id: Mapped[int] = mapped_column(ForeignKey("finished_goods_stock.id"), nullable=False)
    package_id: Mapped[int | None] = mapped_column(ForeignKey("packages.id"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
