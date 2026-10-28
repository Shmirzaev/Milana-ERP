"""Stock quantity adjustment response contract."""

from typing import Optional

from pydantic import BaseModel

from app.libs.enums.inventory import StockMovementType


class StockQuantityAdjustmentOut(BaseModel):
    item_id: int
    previous_quantity: float
    quantity: float
    delta: float
    unit: str
    movement_id: Optional[int] = None
    movement_type: Optional[StockMovementType] = None
