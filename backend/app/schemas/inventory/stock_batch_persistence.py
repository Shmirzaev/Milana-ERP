"""Schema-owned writes for editing a received stock batch.

The stock service retains authorization, validation, lock ordering, linkage
policy, audit and the outer transaction. This operation only applies the
already-decided patch and its corresponding Inventory linkage/ledger writes.
"""

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockBatchQcStatus, StockMovementType
from app.libs.types.inventory import StockBatchEditCommand
from app.schemas import MaterialReservation, WasteRecord
from app.schemas.inventory.inventory import StockBatch, StockMovement


def apply_batch_edit(db: Session, batch: StockBatch, command: StockBatchEditCommand) -> dict[str, int] | None:
    """Apply one validated patch and return relink counts when material changed."""
    for key, value in command.values.items():
        if key == "qc_status" and value is not None:
            assert isinstance(value, StockBatchQcStatus)
            value = value.value
        setattr(batch, key, value)

    relink_counts = None
    if command.relink_item_id is not None:
        for movement in command.item_movements:
            movement.item_id = command.relink_item_id
        relink_counts = {
            "stock_movements": len(command.item_movements),
            "material_reservations": db.query(MaterialReservation).filter(
                MaterialReservation.stock_batch_id == batch.id,
            ).update({MaterialReservation.item_id: command.relink_item_id}, synchronize_session=False),
        }

    return relink_counts


def add_batch_edit_movements(db: Session, batch: StockBatch, command: StockBatchEditCommand) -> None:
    """Append the quantity/warehouse ledger rows after all item relinks."""
    delta = command.target_quantity - command.old_quantity
    if abs(delta) > 1e-9:
        db.add(StockMovement(
            movement_type=(StockMovementType.ADJUSTMENT if delta > 0 else StockMovementType.ISSUE).value,
            item_id=batch.item_id,
            batch_id=batch.id,
            from_warehouse_id=command.old_warehouse_id if delta < 0 else None,
            to_warehouse_id=command.old_warehouse_id if delta > 0 else None,
            quantity=abs(delta),
            unit=command.target_unit,
            reference_type="StockBatchAdjustment",
            reference_id=batch.id,
            created_by=command.actor_id,
        ))
    if command.target_warehouse_id != command.old_warehouse_id and command.target_quantity > 1e-9:
        db.add(StockMovement(
            movement_type=StockMovementType.TRANSFER.value,
            item_id=batch.item_id,
            batch_id=batch.id,
            from_warehouse_id=command.old_warehouse_id,
            to_warehouse_id=command.target_warehouse_id,
            quantity=command.target_quantity,
            unit=command.target_unit,
            reference_type="StockBatchEdit",
            reference_id=batch.id,
            created_by=command.actor_id,
        ))
def relink_batch_waste_items(db: Session, *, batch_id: int, item_id: int) -> int:
    """Update Inventory-owned waste links after the Catalog service participant."""
    return db.query(WasteRecord).filter(
        WasteRecord.batch_id == batch_id,
    ).update({WasteRecord.item_id: item_id}, synchronize_session=False)
