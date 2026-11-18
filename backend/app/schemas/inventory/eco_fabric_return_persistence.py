from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.inventory import StockMovementType
from app.schemas.inventory.eco_transfer import EcoFabricRoll
from app.schemas.inventory.inventory import StockBatch, StockMovement


def apply_eco_fabric_return(
    db: Session, *, row: EcoFabricRoll, batch: StockBatch,
    returned_at: datetime, returned_by: int, operator_name: str,
    return_key: str, quantity: Decimal,
) -> None:
    """Apply a service-approved return in the caller's transaction."""
    row.returned_at = returned_at
    row.returned_by = returned_by
    row.return_operator_name = operator_name
    row.return_key = return_key
    batch.quantity = quantity
    batch.archived_at = None
    batch.archived_by = None
    db.add(StockMovement(
        movement_type=StockMovementType.RETURN.value, item_id=batch.item_id,
        batch_id=batch.id, to_warehouse_id=batch.warehouse_id,
        quantity=row.quantity, unit=row.unit, reference_type="EcoFabricReturn",
        reference_id=row.id, created_by=returned_by,
    ))
