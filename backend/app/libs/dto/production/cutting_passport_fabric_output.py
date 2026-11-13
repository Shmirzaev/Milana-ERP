"""Minimal fabric lookup for an authorized cutting passport order."""
from pydantic import BaseModel


class CuttingPassportFabricOut(BaseModel):
    id: int | None = None
    eco_material_batch_id: int | None = None
    item_id: int
    item_name: str
    item_category: str | None = None
    item_sku: str | None = None
    batch_no: str | None = None
    internal_batch_no: str | None = None
    color: str | None = None
    unit: str
    width: float | None = None
    gsm: float | None = None
    warehouse_name: str | None = None
    image_url: str | None = None
    quantity: float
    reserved_quantity: float
    available_quantity: float
