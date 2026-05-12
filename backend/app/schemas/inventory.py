from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class ItemIn(BaseModel):
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float = 0
    track_batch: bool = False
    is_active: bool = True


class ItemOut(ORMModel):
    id: int
    sku: str
    name: str
    category: str
    unit: str
    default_cost: float
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
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    unit: str
    cost_per_unit: float = 0
    warehouse_id: int
    qc_status: str = "pending"


class StockBatchOut(ORMModel):
    id: int
    item_id: int
    batch_no: str
    supplier_id: Optional[int] = None
    color: Optional[str] = None
    width: Optional[float] = None
    gsm: Optional[float] = None
    quantity: float
    unit: str
    cost_per_unit: float
    received_date: datetime
    warehouse_id: int
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
