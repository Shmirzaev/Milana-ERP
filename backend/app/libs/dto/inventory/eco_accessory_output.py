from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel
from app.libs.enums.eco_accessories import EcoAccessoryStatus


class EcoAccessoryAllocationOut(BaseModel):
    id: int
    batch_id: int
    batch_no: str
    quantity: Decimal
    issued_quantity: Decimal


class EcoAccessoryRequirementOut(BaseModel):
    item_id: int
    sku: str
    item_name: str
    unit: str
    quantity: Decimal
    allocations: list[EcoAccessoryAllocationOut]


class EcoAccessoryPlanOut(BaseModel):
    model_config = {"protected_namespaces": ()}
    id: int | None
    production_order_id: int
    production_no: str
    bso_no: str
    model_id: int
    model_code: str
    planned_quantity: int
    status: EcoAccessoryStatus
    revision: int
    notes: str
    approval_notes: str | None
    approved_by: int | None
    approved_at: datetime | None
    sewing_started: bool
    lines: list[EcoAccessoryRequirementOut]


class EcoAccessoryItemOut(BaseModel):
    id: int
    sku: str
    name: str
    unit: str


class EcoAccessoryOrderListOut(BaseModel):
    items: list[EcoAccessoryPlanOut]
    total: int
