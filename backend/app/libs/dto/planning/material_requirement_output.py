from pydantic import BaseModel, Field

from app.libs.dto.inventory.item_input import ItemComposition


class MaterialRequirement(BaseModel):
    item_id: int
    sku: str
    name: str
    composition: list[ItemComposition] = Field(default_factory=list)
    required_quantity: float
    available_quantity: float
    shortage: float
    unit: str
