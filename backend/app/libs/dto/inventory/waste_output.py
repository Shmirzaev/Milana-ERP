"""Waste record response contract."""

from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class WasteOut(ORMModel):
    id: int
    production_order_id: Optional[int] = None
    work_order_id: Optional[int] = None
    source_department_id: Optional[int] = None
    item_id: Optional[int] = None
    batch_id: Optional[int] = None
    waste_type: str
    quantity: float
    unit: str
    reason: Optional[str] = None
    sellable: bool
    estimated_value: float
    status: str
    created_at: datetime
