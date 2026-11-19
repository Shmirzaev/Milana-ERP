"""Eco balances are isolated from the legacy Milana StockBatch ledger.

Items are shared catalog references. Stock, movements and transfer receipts are
factory-specific and cannot be mutated through the legacy Inventory endpoints.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PkMixin
from app.libs.enums.eco_inventory import FactoryFabricTransferStatus


class EcoMaterialBatch(Base, PkMixin):
    __tablename__ = "eco_material_batches"
    __table_args__ = (
        CheckConstraint("kind IN ('fabric', 'accessory')", name="ck_eco_material_batches_kind"),
        CheckConstraint("quantity >= 0 AND reserved_quantity >= 0 AND reserved_quantity <= quantity", name="ck_eco_material_batches_balance"),
    )
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    reserved_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
    source_stock_batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    receipt_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class EcoMaterialMovement(Base, PkMixin):
    __tablename__ = "eco_material_movements"
    __table_args__ = (
        CheckConstraint("kind IN ('receive', 'transfer_receipt', 'consume', 'issue')", name="ck_eco_material_movements_kind"),
        CheckConstraint("quantity > 0", name="ck_eco_material_movements_positive"),
    )
    batch_id: Mapped[int] = mapped_column(ForeignKey("eco_material_batches.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    production_order_id: Mapped[int | None] = mapped_column(ForeignKey("production_orders.id"), index=True)
    reference_type: Mapped[str | None] = mapped_column(String(64))
    reference_id: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class FactoryFabricTransfer(Base, PkMixin):
    __tablename__ = "factory_fabric_transfers"
    __table_args__ = (
        CheckConstraint("status IN ('in_transit', 'partially_received', 'received')", name="ck_factory_fabric_transfers_status"),
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=FactoryFabricTransferStatus.IN_TRANSIT.value,
                                      server_default=FactoryFabricTransferStatus.IN_TRANSIT.value)
    notes: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    dispatched_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)


class FactoryFabricTransferLine(Base, PkMixin):
    __tablename__ = "factory_fabric_transfer_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0 AND received_quantity >= 0 AND received_quantity <= quantity", name="ck_factory_fabric_transfer_lines_quantity"),
    )
    transfer_id: Mapped[int] = mapped_column(ForeignKey("factory_fabric_transfers.id"), nullable=False, index=True)
    source_batch_id: Mapped[int] = mapped_column(ForeignKey("stock_batches.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt_details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0, server_default="0")
