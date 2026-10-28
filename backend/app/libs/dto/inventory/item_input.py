"""Item master data request contract."""

from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from app.libs.dto.common import StoredUnitCost


class ItemComposition(BaseModel):
    name: str
    percentage: float = Field(ge=0, le=100)


ItemDefaultCost = StoredUnitCost
ItemReorderLevel = Annotated[
    Decimal,
    Field(ge=0, le=Decimal("9999999999.9999"), allow_inf_nan=False),
]


class ItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    default_cost: ItemDefaultCost = Decimal("0")
    reorder_level: ItemReorderLevel = Decimal("0")
    track_batch: bool = False
    is_active: bool = True
    image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)
