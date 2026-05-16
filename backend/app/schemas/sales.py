from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class SalesOrderItemIn(BaseModel):
    model_id: int
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: int
    unit_price: float = 0
    printing_required: bool = False
    source_type: str = "produce_new"
    notes: Optional[str] = None


class SalesOrderItemOut(ORMModel):
    id: int
    sales_order_id: int
    model_id: int
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: int
    unit_price: float
    printing_required: bool
    source_type: str
    notes: Optional[str] = None


class SalesOrderIn(BaseModel):
    customer_id: Optional[int] = None
    order_type: str = "client_order"
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    items: list[SalesOrderItemIn] = []


class SalesOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class SalesOrderOut(ORMModel):
    id: int
    order_no: str
    customer_id: Optional[int] = None
    order_type: str
    status: str
    deadline: Optional[datetime] = None
    total_amount: float
    planning_estimated_material_cost: Optional[float] = None
    planning_estimated_lead_time_minutes: Optional[int] = None
    planning_estimate_comment: Optional[str] = None
    planning_estimate_submitted_at: Optional[datetime] = None
    planning_estimate_submitted_by: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime


class SalesOrderDetail(SalesOrderOut):
    items: list[SalesOrderItemOut] = []


class ShipmentIn(BaseModel):
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    notes: Optional[str] = None


class ShipmentOut(ORMModel):
    id: int
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    shipment_no: str
    status: str
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime


class InvoiceIn(BaseModel):
    sales_order_id: int
    amount: float


class InvoiceOut(ORMModel):
    id: int
    sales_order_id: int
    invoice_no: str
    amount: float
    status: str
    issued_at: Optional[datetime] = None
    due_date: Optional[datetime] = None


class PaymentIn(BaseModel):
    invoice_id: int
    amount: float
    payment_method: Optional[str] = None
    notes: Optional[str] = None


class PaymentOut(ORMModel):
    id: int
    invoice_id: int
    amount: float
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
