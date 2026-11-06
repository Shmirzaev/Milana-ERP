"""Item master data response contract."""

from typing import Optional

from pydantic import Field

from app.libs.dto.common import ORMModel
from app.libs.dto.inventory.item_input import ItemComposition


class ItemOut(ORMModel):
    id: int
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float
    reorder_level: float
    track_batch: bool
    is_active: bool
    image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)
