"""Mapped writes for a service-approved material batch restoration."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.schemas.inventory.inventory import StockBatch, StockMovement


def restore_material_batch(db: Session, batch: StockBatch, *, quantity: Decimal, user_id: int | None) -> None:
    """Apply the approved restoration and queue its movement in the supplied session."""
    batch.quantity = quantity
    batch.archived_at = None
    batch.archived_by = None
    batch.qc_status = StockBatchQcStatus.PENDING.value
    batch.roll_weights_kg = []
    batch.roll_lengths_m = []
    batch.piece_count = None
    db.add(StockMovement(
        movement_type=StockMovementType.RETURN.value, item_id=batch.item_id, batch_id=batch.id,
        to_warehouse_id=batch.warehouse_id, quantity=quantity, unit=batch.unit,
        reference_type="StockBatchRestore", reference_id=batch.id, created_by=user_id,
    ))
