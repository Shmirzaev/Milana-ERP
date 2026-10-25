from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.libs.dto.purchasing.purchase_quantity import PurchaseQuantity


class PurchaseRequestLineIn(BaseModel):
    item_id: int
    required_quantity: float = 0
    requested_quantity: Optional[float] = None
    unit: Optional[str] = None
    available_quantity: float = 0
    shortage_quantity: Optional[float] = None
    preferred_supplier_id: Optional[int] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseRequestIn(BaseModel):
    sales_order_id: Optional[int] = None
    production_order_id: Optional[int] = None
    status: str = "pending_approval"
    notes: Optional[str] = None
    lines: list[PurchaseRequestLineIn] = Field(max_length=1000)


class PurchaseRequestApprovalLineIn(BaseModel):
    purchase_request_line_id: int
    material_name: str
    preferred_supplier_id: int
    photo_url: str


class PurchaseRequestApprovalIn(BaseModel):
    lines: list[PurchaseRequestApprovalLineIn] = Field(max_length=1000)


class PurchaseRequestOrderLineIn(BaseModel):
    purchase_request_line_id: int
    ordered_quantity: PurchaseQuantity


class PurchaseRequestOrderIn(BaseModel):
    expected_date: datetime
    lines: list[PurchaseRequestOrderLineIn] = Field(max_length=1000)
