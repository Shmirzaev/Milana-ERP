from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class PurchaseRequestLineOut(ORMModel):
    id: int
    purchase_request_id: int
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    required_quantity: float
    requested_quantity: float
    unit: str
    available_quantity: float
    shortage_quantity: float
    preferred_supplier_id: Optional[int] = None
    preferred_supplier_name: Optional[str] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseRequestOut(ORMModel):
    id: int
    request_no: str
    status: str
    sales_order_id: Optional[int] = None
    sales_order_no: Optional[str] = None
    production_order_id: Optional[int] = None
    production_no: Optional[str] = None
    requested_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseRequestLineOut] = []
