"""Accessory return request contract."""

from typing import Optional

from app.libs.dto.inventory.stock_batch_input import StockBatchIn


class AccessoryReturnIn(StockBatchIn):
    production_order_id: int
    return_condition: Optional[str] = "used"
