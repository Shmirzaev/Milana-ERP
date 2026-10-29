"""Stock line read model."""

from typing import Optional

from pydantic import BaseModel


class StockLine(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    warehouse_id: int
    quantity: float
    unit: str
    reserved_quantity: float = 0
    available_quantity: float = 0
