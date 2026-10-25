from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.dto.inventory.item_output import ItemOut


class ModelBOMOut(ORMModel):
    id: int
    item_id: Optional[int] = None
    material_name: Optional[str] = None
    material_role: Optional[str] = None
    item: Optional[ItemOut] = None
    stock_batch_id: Optional[int] = None
    stock_batch_no: Optional[str] = None
    stock_batch_image_url: Optional[str] = None
    stock_batch_color: Optional[str] = None
    size: Optional[str] = None
    color: Optional[str] = None
    photo_url: Optional[str] = None
    quantity_per_piece: float
    unit: str
    waste_percent: float
