from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.schemas.common import ORMModel


class ItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float = 0
    reorder_level: float = 0
    track_batch: bool = False
    is_active: bool = True


class ItemOut(ORMModel):
    id: int
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float
    reorder_level: float
    track_batch: bool
    is_active: bool


class WarehouseIn(BaseModel):
    name: str
    type: str
    department_id: Optional[int] = None


class WarehouseOut(ORMModel):
    id: int
    name: str
    type: str
    department_id: Optional[int] = None


class StockBatchIn(BaseModel):
    item_id: int
    batch_no: str
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    old_code: Optional[str] = None
    color_code: Optional[str] = None
    color_status: Optional[str] = None
    order_no: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    piece_count: Optional[int] = None
    processes: Optional[str] = None
    unit: str
    cost_per_unit: float = 0
    warehouse_id: int
    qc_status: str = "pending"


class StockBatchOut(ORMModel):
    id: int
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    batch_no: str
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
    processes: Optional[str] = None
    unit: str
    cost_per_unit: float
    received_date: datetime
    warehouse_id: int
    warehouse_name: Optional[str] = None
    qc_status: str


class StockMovementIn(BaseModel):
    movement_type: str
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None


class StockMovementOut(ORMModel):
    id: int
    movement_type: str
    item_id: int
    batch_id: Optional[int] = None
    from_warehouse_id: Optional[int] = None
    to_warehouse_id: Optional[int] = None
    quantity: float
    unit: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime


class StockLine(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    warehouse_id: int
    quantity: float
    unit: str


class AccessoryIssuePlanRow(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    category: str
    unit: str
    required_quantity: float
    issued_quantity: float
    remaining_quantity: float
    available_quantity: float
    shortage: float


class AccessoryIssuePlanOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    rows: list[AccessoryIssuePlanRow]


class AccessoryIssueLineIn(BaseModel):
    item_id: int
    quantity: float
    unit: Optional[str] = None


class AccessoryIssueIn(BaseModel):
    production_order_id: int
    lines: list[AccessoryIssueLineIn]
    notes: Optional[str] = None


class AccessoryIssueLineOut(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    quantity: float
    unit: str


class AccessoryIssueOut(BaseModel):
    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    issued: list[AccessoryIssueLineOut]


class AccessoryIssueSummaryRow(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    item_id: int
    item_sku: str
    item_name: str
    category: str
    unit: str
    issued_quantity: float
    movement_count: int
    first_issued_at: Optional[datetime] = None
    last_issued_at: Optional[datetime] = None
