"""Persistence for stock batch correction; transaction remains with the caller."""
from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockMovementType
from app.libs.types.inventory import StockBatchEditValues
from app.schemas.inventory.inventory import MaterialReservation, StockBatch, StockMovement



def apply_values(db: Session, batch: StockBatch, values: StockBatchEditValues) -> None:
    for key, value in values.items():
        setattr(batch, key, value)


def relink_movements(db: Session, movements: list[StockMovement], item_id: int) -> int:
    for movement in movements:
        movement.item_id = item_id
    return len(movements)


def relink_reservations(db: Session, batch_id: int, item_id: int) -> int:
    return db.query(MaterialReservation).filter(
        MaterialReservation.stock_batch_id == batch_id,
    ).update({MaterialReservation.item_id: item_id}, synchronize_session=False)


def add_movement(
    db: Session, *, movement_type: StockMovementType, item_id: int,
    batch_id: int, from_warehouse_id: int | None, to_warehouse_id: int | None,
    quantity: float, unit: str, reference_type: str, reference_id: int,
    created_by: int | None,
) -> None:
    db.add(StockMovement(
        movement_type=movement_type.value, item_id=item_id, batch_id=batch_id,
        from_warehouse_id=from_warehouse_id, to_warehouse_id=to_warehouse_id,
        quantity=quantity, unit=unit, reference_type=reference_type,
        reference_id=reference_id, created_by=created_by,
    ))
