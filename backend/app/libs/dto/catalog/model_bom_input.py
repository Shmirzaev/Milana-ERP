from typing import Optional

from pydantic import BaseModel, Field


class ModelBOMIn(BaseModel):
    item_id: Optional[int] = None
    material_name: Optional[str] = Field(None, max_length=255)
    material_role: Optional[str] = Field(None, max_length=16)
    stock_batch_id: Optional[int] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float = 0
