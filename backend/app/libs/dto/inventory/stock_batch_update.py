"""Stock batch correction request contract."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.libs.dto.common import StoredUnitCost


class StockBatchUpdate(BaseModel):
    length_m: Optional[float] = Field(default=None, gt=0, lt=100000000000, allow_inf_nan=False)
    item_id: Optional[int] = None
    batch_no: Optional[str] = None
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: Optional[float] = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    piece_count: Optional[int] = Field(default=None, ge=0)
    processes: Optional[str] = None
    unit: Optional[str] = None
    cost_per_unit: Optional[StoredUnitCost] = None
    image_url: Optional[str] = None
    received_date: Optional[datetime] = None
    warehouse_id: Optional[int] = None
    qc_status: Optional[str] = None
