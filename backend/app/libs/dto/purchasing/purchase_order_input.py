from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.libs.dto.common import StoredUnitCost
from app.libs.dto.purchasing.purchase_quantity import PurchaseQuantity, PurchaseReceiptQuantity


class PurchaseOrderLineIn(BaseModel):
    item_id: int
    ordered_quantity: PurchaseQuantity
    unit: Optional[str] = None
    unit_cost: StoredUnitCost = Decimal("0")
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseOrderIn(BaseModel):
    purchase_request_id: Optional[int] = None
    supplier_id: Optional[int] = None
    expected_date: Optional[datetime] = None
    notes: Optional[str] = None
    lines: list[PurchaseOrderLineIn] = Field(max_length=1000)


class PurchaseOrderReceiveLineIn(BaseModel):
    purchase_order_line_id: int
    received_quantity: PurchaseReceiptQuantity
    batch_no: str
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    cost_per_unit: Optional[StoredUnitCost] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list, max_length=1000)
    processes: Optional[str] = None
    qc_status: str = "passed"


class PurchaseOrderReceiveIn(BaseModel):
    supplier_id: Optional[int] = None
    close_order: bool = False
    lines: list[PurchaseOrderReceiveLineIn] = Field(max_length=1000)
