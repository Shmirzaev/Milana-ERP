"""Stock batch response contract."""

from datetime import datetime
from typing import Optional

from pydantic import Field

from app.libs.dto.common import ORMModel
from app.libs.enums.inventory import StockBatchQcStatus


class StockBatchOut(ORMModel):
    offsite_roll_numbers: list[int] = Field(default_factory=list)
    available_piece_count: Optional[int] = None
    roll_lengths_m: list[float | None] = Field(default_factory=list)
    length_m: Optional[float] = None
    id: int
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    item_category: Optional[str] = None
    batch_no: str
    internal_batch_no: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list)
    processes: Optional[str] = None
    unit: str
    cost_per_unit: float
    image_url: Optional[str] = None
    received_date: datetime
    warehouse_id: int
    warehouse_name: Optional[str] = None
    qc_status: StockBatchQcStatus
    reserved_quantity: float = 0
    available_quantity: float = 0
    active_reservations: list[dict] = []
