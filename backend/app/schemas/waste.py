from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class WasteIn(BaseModel):
    production_order_id: Optional[int] = None
    work_order_id: Optional[int] = None
    source_department_id: Optional[int] = None
    item_id: Optional[int] = None
    batch_id: Optional[int] = None
    waste_type: str
    quantity: float
    unit: str
    reason: Optional[str] = None
    sellable: bool = False
    estimated_value: float = 0


class WasteOut(ORMModel):
    id: int
    production_order_id: Optional[int] = None
    work_order_id: Optional[int] = None
    source_department_id: Optional[int] = None
    item_id: Optional[int] = None
    batch_id: Optional[int] = None
    waste_type: str
    quantity: float
    unit: str
    reason: Optional[str] = None
    sellable: bool
    estimated_value: float
    status: str
    created_at: datetime


class WasteSaleIn(BaseModel):
    buyer_name: str
    quantity: float
    unit_price: float


class WasteSaleOut(ORMModel):
    id: int
    waste_record_id: int
    buyer_name: str
    quantity: float
    unit_price: float
    total_amount: float
    sold_at: Optional[datetime] = None


class WasteDisposalIn(BaseModel):
    reason: Optional[str] = None


class WasteDisposalOut(ORMModel):
    id: int
    waste_record_id: int
    reason: Optional[str] = None
    status: str
    requested_by: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    proof_file_url: Optional[str] = None
