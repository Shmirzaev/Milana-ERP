"""Stock batch restoration request contract."""

from decimal import Decimal

from pydantic import BaseModel, Field


class StockBatchRestoreIn(BaseModel):
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=500)
