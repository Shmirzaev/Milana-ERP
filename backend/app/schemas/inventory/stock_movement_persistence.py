"""Mapped insert for stock movements; the caller owns audit and commit."""
from decimal import Decimal
from datetime import datetime

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockMovementType
from app.schemas.inventory.inventory import StockBatch, StockMovement


def set_batch_quantity(db: Session, batch: StockBatch, quantity: Decimal) -> None:
    """Apply a service-calculated quantity in the caller's transaction."""
    batch.quantity = quantity


def set_batch_warehouse(db: Session, batch: StockBatch, warehouse_id: int) -> None:
    """Apply a service-approved batch relocation."""
    batch.warehouse_id = warehouse_id


def archive_batch(db: Session, batch: StockBatch, *, archived_at: datetime, user_id: int | None) -> None:
    """Apply the archive fields after the service has decided to archive."""
    batch.quantity = 0
    batch.archived_at = archived_at
    batch.archived_by = user_id


def insert_stock_movement(
    db: Session,
    *,
    movement_type: StockMovementType,
    item_id: int,
    batch_id: int | None,
    from_warehouse_id: int | None,
    to_warehouse_id: int | None,
    quantity: Decimal,
    unit: str,
    reference_type: str | None,
    reference_id: int | None,
    created_by: int | None,
) -> StockMovement:
    """Use the supplied Session and the unchanged String/FK storage."""
    movement = StockMovement(
        movement_type=movement_type.value,
        item_id=item_id,
        batch_id=batch_id,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        quantity=quantity,
        unit=unit,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    db.add(movement)
    db.flush()
    return movement
