from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


PurchaseOrderQuantity = Annotated[
    Decimal,
    Field(gt=0, le=Decimal("9999999999.9999"), allow_inf_nan=False),
]
PurchaseReceiptQuantity = Annotated[
    float,
    Field(gt=0, le=9_999_999_999.9999, allow_inf_nan=False),
]
PurchaseOrderUnitCost = Annotated[
    float,
    Field(ge=-99_999_999.9999, le=99_999_999.9999, allow_inf_nan=False),
]
PurchaseReceiptUnitCost = Annotated[
    float,
    Field(ge=0, le=99_999_999.9999, allow_inf_nan=False),
]
PurchaseRequestQuantity = Annotated[
    Decimal,
    Field(
        ge=Decimal("-9999999999.9999"),
        le=Decimal("9999999999.9999"),
        allow_inf_nan=False,
    ),
]


class PurchaseRequestLineIn(BaseModel):
    item_id: int
    required_quantity: PurchaseRequestQuantity = Decimal("0")
    requested_quantity: Optional[PurchaseRequestQuantity] = None
    unit: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 32})
    available_quantity: PurchaseRequestQuantity = Decimal("0")
    shortage_quantity: Optional[PurchaseRequestQuantity] = None
    preferred_supplier_id: Optional[int] = None
    material_name: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 255})
    photo_url: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 500})
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


class PurchaseRequestPageOut(BaseModel):
    rows: list[PurchaseRequestOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class PurchaseOrderLineIn(BaseModel):
    item_id: int
    ordered_quantity: PurchaseOrderQuantity
    unit: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 32})
    unit_cost: PurchaseOrderUnitCost = 0
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    material_name: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 255})
    photo_url: Optional[str] = Field(default=None, json_schema_extra={"maxLength": 500})
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


class PurchaseOrderPageOut(BaseModel):
    rows: list[PurchaseOrderOut]
    total: int
    page: int
    page_size: int
    has_more: bool


class PurchaseOrderReceiveLineIn(BaseModel):
    purchase_order_line_id: int
    received_quantity: PurchaseReceiptQuantity
    batch_no: str
    warehouse_id: Optional[int] = None
    supplier_id: Optional[int] = None
    cost_per_unit: Optional[PurchaseReceiptUnitCost] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = Field(default=None, ge=-99_999_999.99, le=99_999_999.99, allow_inf_nan=False)
    gsm: Optional[float] = Field(default=None, ge=-99_999_999.999999, le=99_999_999.999999, allow_inf_nan=False)
    piece_count: Optional[int] = None
    roll_weights_kg: list[float] = Field(default_factory=list, max_length=1000)
    processes: Optional[str] = None
    qc_status: str = "passed"


class PurchaseOrderReceiveIn(BaseModel):
    supplier_id: Optional[int] = None
    close_order: bool = False
    lines: list[PurchaseOrderReceiveLineIn]


class PurchaseRequestApprovalLineIn(BaseModel):
    purchase_request_line_id: int
    material_name: str
    preferred_supplier_id: int
    photo_url: str


class PurchaseRequestApprovalIn(BaseModel):
    lines: list[PurchaseRequestApprovalLineIn]


class PurchaseRequestOrderLineIn(BaseModel):
    purchase_request_line_id: int
    ordered_quantity: PurchaseOrderQuantity


class PurchaseRequestOrderIn(BaseModel):
    expected_date: datetime
    lines: list[PurchaseRequestOrderLineIn]
