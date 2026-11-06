"""Stock movement request contract."""

from typing import Optional

from pydantic import BaseModel

from app.libs.enums.inventory import StockMovementType


class StockMovementIn(BaseModel):
    movement_type: StockMovementType
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
