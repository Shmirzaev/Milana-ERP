from typing import Optional
from pydantic import BaseModel

from app.schemas.common import ORMModel


class SewingFlowIn(BaseModel):
    name: str
    code: str
    description: Optional[str] = None
    capacity_per_day: int = 0
    supervisor_id: Optional[int] = None
    is_active: bool = True


class SewingFlowUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    capacity_per_day: Optional[int] = None
    supervisor_id: Optional[int] = None
    is_active: Optional[bool] = None


class SewingFlowOut(ORMModel):
    id: int
    name: str
    code: str
    description: Optional[str] = None
    capacity_per_day: int
    supervisor_id: Optional[int] = None
    is_active: bool


class SewingFlowWithLoad(SewingFlowOut):
    """Sewing flow + the currently-assigned work orders summary."""
    active_work_orders: int = 0
    planned_units: int = 0
    completed_units: int = 0
