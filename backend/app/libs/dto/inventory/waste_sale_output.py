"""Waste sale response contract."""

from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class WasteSaleOut(ORMModel):
    id: int
    waste_record_id: int
    buyer_name: str
    quantity: float
    unit_price: float
    total_amount: float
    sold_at: Optional[datetime] = None
