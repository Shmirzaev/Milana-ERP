from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.enums.purchasing import PurchaseOrderStatus


class PurchaseOrderLineOut(ORMModel):
    id: int
    purchase_order_id: int
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    ordered_quantity: float
    received_quantity: float
    remaining_quantity: float
    unit: str
    unit_cost: float
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    material_name: Optional[str] = None
    photo_url: Optional[str] = None
    notes: Optional[str] = None


class PurchaseOrderOut(ORMModel):
    id: int
    po_no: str
    purchase_request_id: Optional[int] = None
    request_no: Optional[str] = None
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    status: str
    ordered_by: Optional[int] = None
    expected_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseOrderLineOut] = []


class PurchaseOrderCreationOut(PurchaseOrderOut):
    """Result of creating or converting an order, with a canonical status."""

    status: PurchaseOrderStatus
