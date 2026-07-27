from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class SewingAssignmentIn(BaseModel):
    work_order_id: int
    production_batch_id: Optional[int] = None
    sewing_flow_id: int
    quantity: int
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    notes: Optional[str] = None


class SewingAssignmentUpdate(BaseModel):
    production_batch_id: Optional[int] = None
    sewing_flow_id: Optional[int] = None
    quantity: Optional[int] = None
    completed_qty: Optional[int] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SewingAssignmentOut(ORMModel):
    id: int
    work_order_id: int
    production_batch_id: Optional[int] = None
    sewing_flow_id: int
    quantity: int
    completed_qty: int
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
