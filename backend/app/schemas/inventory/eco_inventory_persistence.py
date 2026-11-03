"""Explicit mapped writes in the caller's transaction; no policy or commits."""
from decimal import Decimal
from sqlalchemy.orm import Session

from app.libs.enums.eco_inventory import EcoMaterialKind, EcoMaterialMovementKind, FactoryFabricTransferStatus
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement, FactoryFabricTransfer, FactoryFabricTransferLine


def insert_batch(db: Session, *, item_id: int, kind: EcoMaterialKind, batch_no: str, color: str | None,
                 unit: str, quantity: Decimal, created_by: int, source_stock_batch_id: int | None = None) -> EcoMaterialBatch:
    row = EcoMaterialBatch(item_id=item_id, kind=kind.value, batch_no=batch_no, color=color,
                           unit=unit, quantity=quantity, reserved_quantity=Decimal(0), created_by=created_by,
                           source_stock_batch_id=source_stock_batch_id)
    db.add(row)
    db.flush()
    return row


def set_batch_balance(db: Session, batch: EcoMaterialBatch, *, quantity: Decimal, reserved_quantity: Decimal) -> None:
    batch.quantity = quantity
    batch.reserved_quantity = reserved_quantity


def insert_movement(db: Session, *, batch_id: int, kind: EcoMaterialMovementKind, quantity: Decimal,
                    created_by: int, production_order_id: int | None = None, reference_type: str | None = None,
                    reference_id: int | None = None, notes: str | None = None) -> EcoMaterialMovement:
    row = EcoMaterialMovement(batch_id=batch_id, kind=kind.value, quantity=quantity, created_by=created_by,
                              production_order_id=production_order_id, reference_type=reference_type,
                              reference_id=reference_id, notes=notes)
    db.add(row)
    db.flush()
    return row


def insert_transfer(db: Session, *, created_by: int, notes: str | None) -> FactoryFabricTransfer:
    row = FactoryFabricTransfer(dispatched_by=created_by, notes=notes, status=FactoryFabricTransferStatus.IN_TRANSIT.value)
    db.add(row)
    db.flush()
    return row


def insert_transfer_line(db: Session, *, transfer_id: int, source_batch_id: int, item_id: int,
                         item_name: str, batch_no: str, color: str | None, unit: str,
                         quantity: Decimal) -> FactoryFabricTransferLine:
    row = FactoryFabricTransferLine(transfer_id=transfer_id, source_batch_id=source_batch_id, item_id=item_id,
                                    item_name=item_name, batch_no=batch_no, color=color, unit=unit,
                                    quantity=quantity, received_quantity=Decimal(0))
    db.add(row)
    db.flush()
    return row


def set_transfer_received(db: Session, line: FactoryFabricTransferLine, quantity: Decimal) -> None:
    line.received_quantity = quantity


def set_transfer_status(db: Session, transfer: FactoryFabricTransfer, status: FactoryFabricTransferStatus) -> None:
    transfer.status = status.value
