"""Explicit input identities; ECO primary keys never occupy central foreign keys."""
from pydantic import BaseModel, Field, model_validator


class FabricSourceIn(BaseModel):
    stock_batch_id: int | None = Field(default=None, gt=0)
    eco_material_batch_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def one_source(self):
        if (self.stock_batch_id is None) == (self.eco_material_batch_id is None):
            raise ValueError("Select exactly one central or Eco Cotton fabric source")
        return self
