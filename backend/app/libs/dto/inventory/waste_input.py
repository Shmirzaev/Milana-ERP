"""Waste record request contract."""

from typing import Optional

from pydantic import BaseModel


class WasteIn(BaseModel):
    production_order_id: Optional[int] = None
    work_order_id: Optional[int] = None
    source_department_id: Optional[int] = None
    item_id: Optional[int] = None
    batch_id: Optional[int] = None
    waste_type: str
    quantity: float
    unit: str
    reason: Optional[str] = None
    sellable: bool = False
    estimated_value: float = 0
