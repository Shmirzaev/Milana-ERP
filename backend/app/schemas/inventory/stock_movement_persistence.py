"""Mapped insert for stock movements; the caller owns audit and commit."""
from decimal import Decimal
from datetime import datetime

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.libs.types.inventory import StockConsumptionCommand
from app.schemas.inventory.inventory import StockBatch, StockMovement


def set_batch_quantity(db: Session, batch: StockBatch, quantity: Decimal | float) -> None:
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


def add_adjustment_batch(
    db: Session,
    *,
    item_id: int,
    batch_no: str,
    quantity: float,
    unit: str,
    cost_per_unit: Decimal,
    warehouse_id: int,
    qc_status: StockBatchQcStatus,
) -> StockBatch:
    """Insert an adjustment-created batch and flush for its movement FK."""
    batch = StockBatch(
        item_id=item_id,
        batch_no=batch_no,
        quantity=quantity,
        unit=unit,
        cost_per_unit=cost_per_unit,
        warehouse_id=warehouse_id,
        qc_status=qc_status.value,
    )
    db.add(batch)
    db.flush()
    return batch


def add_stock_adjustment_movement(
    db: Session,
    *,
    movement_type: StockMovementType,
    item_id: int,
    batch_id: int | None,
    from_warehouse_id: int | None,
    to_warehouse_id: int | None,
    quantity: float,
    unit: str,
    created_by: int | None,
) -> StockMovement:
    """Queue an adjustment ledger row; the service owns the later flush."""
    movement = StockMovement(
        movement_type=movement_type.value,
        item_id=item_id,
        batch_id=batch_id,
        from_warehouse_id=from_warehouse_id,
        to_warehouse_id=to_warehouse_id,
        quantity=quantity,
        unit=unit,
        reference_type="StockAdjustment",
        created_by=created_by,
    )
    db.add(movement)
    return movement


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


def record_stock_consumption(
    db: Session,
    *,
    batch: StockBatch | None,
    command: StockConsumptionCommand,
) -> StockMovement:
    """Apply one service-calculated consumption and append its ledger row.

    The caller owns batch selection/locking, availability checks, FIFO order,
    archive policy and the outer transaction. This writer does not flush.
    """
    if batch is not None:
        batch.quantity = float(batch.quantity or 0) - command.quantity

    movement = StockMovement(
        movement_type=command.movement_type.value,
        item_id=command.item_id,
        batch_id=command.batch_id,
        from_warehouse_id=command.from_warehouse_id,
        to_warehouse_id=None,
        quantity=command.quantity,
        unit=command.unit,
        reference_type=command.reference_type,
        reference_id=command.reference_id,
        created_by=command.actor_id,
    )
    db.add(movement)
    return movement
