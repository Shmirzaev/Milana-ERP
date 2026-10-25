"""Stock movement response contract."""

from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class StockMovementOut(ORMModel):
    id: int
    movement_type: str
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime
