import math
from decimal import Decimal
from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, SchemaModel
from app.schemas.shipment_review import ShipmentTransportDetails


def _swap_nonfinite_amount(value: object) -> object:
    """Replace a nonfinite number with a serializable stand-in before validation.

    FastAPI echoes the offending input into the 422 body, and `inf`/`nan` cannot be
    JSON-encoded, so rejecting such a value directly makes the error response itself
    fail to serialize and the caller sees a 500 instead of a validation error.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
        return "non-finite number"
    return value


class SalesOrderItemIn(SchemaModel):
    model_id: int
    brand_id: Optional[int] = None
    collection_id: Optional[int] = None
    color: str
    size: str
    quantity: Optional[int] = Field(default=None, ge=0, le=2_147_483_647)
    requested_pack_count: Optional[int] = Field(default=None, gt=0, le=2_147_483_647, strict=True)
    # When omitted, the backend uses the selected variant's current selling price.
    # An explicitly entered zero remains an intentional zero-price override.
    unit_price: Optional[float] = Field(default=None, ge=0, le=9_999_999_999.99, allow_inf_nan=False)
    printing_required: bool = False
    source_type: str = "produce_new"
    notes: Optional[str] = None


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


class SalesOrderPrintingAttachment(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None


class SalesOrderIn(BaseModel):
    customer_id: Optional[int] = None
    order_type: str = "client_order"
    deadline: Optional[datetime] = None
    printing_instructions: Optional[str] = None
    printing_attachments: list[SalesOrderPrintingAttachment] = []
    notes: Optional[str] = None
    items: list[SalesOrderItemIn] = []


class SalesOrderUpdate(BaseModel):
    customer_id: Optional[int] = None
    deadline: Optional[datetime] = None
    printing_instructions: Optional[str] = None
    printing_attachments: Optional[list[SalesOrderPrintingAttachment]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


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


class ShipmentIn(BaseModel):
    manual: bool = False
    request_key: UUID | None = None
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    notes: Optional[str] = None
    transport_details: ShipmentTransportDetails | None = None


class ShipmentOut(ORMModel):
    id: int
    sales_order_id: Optional[int] = None
    customer_id: Optional[int] = None
    shipment_no: str
    status: str
    shipped_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    notes: Optional[str] = None
    transport_details: ShipmentTransportDetails | None = None
    sales_order_no: Optional[str] = None
    customer_name: Optional[str] = None
    shipment_type: str = "sales_order"
    packages_count: int = 0
    total_qty: int = 0
    required_count: int = 0
    scanned_count: int = 0
    remaining_count: int = 0
    is_complete: bool = False
    created_at: datetime


class ShipmentScanIn(BaseModel):
    code: str


class ShipmentScanOut(BaseModel):
    ok: bool
    sign: str
    code: str
    message: str
    package_id: Optional[int] = None
    package_no: Optional[str] = None
    package_model_code: Optional[str] = None
    required_count: int = 0
    scanned_count: int = 0
    remaining_count: int = 0
    is_complete: bool = False


class InvoiceIn(BaseModel):
    sales_order_id: int
    # `invoices.amount` is NUMERIC(14, 2) with `amount >= 0`; max_digits/decimal_places
    # mirror that column so nonfinite, sub-cent and out-of-range values never reach a write.
    amount: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False
    )

    @field_validator("amount", mode="before")
    @classmethod
    def _swap_nonfinite_invoice_amount(cls, value: object) -> object:
        return _swap_nonfinite_amount(value)


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
    # `payments.amount` is NUMERIC(14, 2) with `amount > 0`, so the smallest
    # representable payment is one cent and nothing wider than the column is accepted.
    amount: Decimal = Field(ge=0.01, max_digits=14, decimal_places=2, allow_inf_nan=False)

    @field_validator("amount", mode="before")
    @classmethod
    def _swap_nonfinite_payment_amount(cls, value: object) -> object:
        return _swap_nonfinite_amount(value)
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None


class PaymentOut(ORMModel):
    id: int
    invoice_id: int
    amount: float
    payment_method: Optional[str] = None
    paid_at: Optional[datetime] = None
