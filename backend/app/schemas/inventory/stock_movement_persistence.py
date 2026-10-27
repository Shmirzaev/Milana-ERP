"""Mapped insert for stock movements; the caller owns audit and commit."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockMovementType
from app.schemas.inventory.inventory import StockMovement


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
