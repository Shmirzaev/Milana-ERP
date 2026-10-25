from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.libs.dto.common import ORMModel
from app.libs.dto.sales.sales_order_input import SalesOrderPrintingAttachment


class SalesOrderItemModelRef(BaseModel):
    id: int
    code: str
    name: str
    translations: Optional[dict] = None


class SalesOrderCustomerRef(BaseModel):
    id: int
    name: str


class SalesOrderItemOut(ORMModel):
    id: int
    sales_order_id: int
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: int
    requested_pack_count: Optional[int] = None
    unit_price: float
    printing_required: bool
    source_type: str
    notes: Optional[str] = None
    model: Optional[SalesOrderItemModelRef] = None


class SalesOrderOut(ORMModel):
    id: int
    order_no: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    order_type: str
    status: str
    deadline: Optional[datetime] = None
    total_amount: float
    planning_estimated_material_cost: Optional[float] = None
    planning_estimated_labor_cost: Optional[float] = None
    planning_estimated_electricity_cost: Optional[float] = None
    planning_estimated_other_cost: Optional[float] = None
    planning_estimated_net_cost: Optional[float] = None
    planning_suggested_price_15: Optional[float] = None
    planning_suggested_price_20: Optional[float] = None
    planning_estimated_lead_time_minutes: Optional[int] = None
    planning_estimate_comment: Optional[str] = None
    planning_estimate_submitted_at: Optional[datetime] = None
    planning_estimate_submitted_by: Optional[int] = None
    printing_instructions: Optional[str] = None
    printing_attachments: Optional[list[SalesOrderPrintingAttachment]] = None
    notes: Optional[str] = None
    customer: Optional[SalesOrderCustomerRef] = None
    created_at: datetime


class SalesOrderDetail(SalesOrderOut):
    items: list[SalesOrderItemOut] = []
