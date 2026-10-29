"""Accessory issue request contracts."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class AccessoryIssueLineIn(BaseModel):
    item_id: Optional[int] = None
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4, allow_inf_nan=False)
    unit: Optional[str] = None
    manual: bool = False


class AccessoryIssueIn(BaseModel):
    production_order_id: int
    lines: list[AccessoryIssueLineIn]
    notes: Optional[str] = None
