"""Stock quantity adjustment request contract."""

from typing import Optional

from pydantic import BaseModel, Field


class StockQuantityAdjustmentIn(BaseModel):
    quantity: float = Field(ge=0)
    unit: Optional[str] = None
