from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.schemas.common import ORMModel


class PurchaseRequestLineIn(BaseModel):
    item_id: int
    required_quantity: float
    requested_quantity: Optional[float] = None
    unit: Optional[str] = None
    available_quantity: float = 0
    shortage_quantity: Optional[float] = None
    preferred_supplier_id: Optional[int] = None
    notes: Optional[str] = None


class PurchaseRequestIn(BaseModel):
    sales_order_id: Optional[int] = None
    production_order_id: Optional[int] = None
    status: str = "pending_approval"
    notes: Optional[str] = None
    lines: list[PurchaseRequestLineIn]


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


class PurchaseOrderLineIn(BaseModel):
    item_id: int
    ordered_quantity: float
    unit: Optional[str] = None
    unit_cost: float = 0
    warehouse_id: Optional[int] = None
    notes: Optional[str] = None


class PurchaseOrderIn(BaseModel):
    purchase_request_id: Optional[int] = None
    supplier_id: Optional[int] = None
    expected_date: Optional[datetime] = None
    notes: Optional[str] = None
    lines: list[PurchaseOrderLineIn]


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


class PurchaseOrderReceiveLineIn(BaseModel):
    purchase_order_line_id: int
    received_quantity: float
    batch_no: str
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    cost_per_unit: Optional[float] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    piece_count: Optional[int] = None
    processes: Optional[str] = None
    qc_status: str = "passed"


class PurchaseOrderReceiveIn(BaseModel):
    supplier_id: Optional[int] = None
    lines: list[PurchaseOrderReceiveLineIn]
