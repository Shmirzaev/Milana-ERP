"""Stock batch roll weight replacement request contract."""

from pydantic import BaseModel, Field


class StockBatchRollWeightsIn(BaseModel):
    roll_weights_kg: list[float] = Field(min_length=1, max_length=1000)
