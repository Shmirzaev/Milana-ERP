"""Material reservation response contracts."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.libs.dto.common import ORMModel
from app.libs.dto.inventory.item_input import ItemComposition
from app.libs.enums.inventory import (
    MaterialReservationSource,
    MaterialReservationStatus,
    MaterialReservationType,
)


class MaterialReservationOut(ORMModel):
    id: int
    reservation_no: str
    production_order_id: int
    sales_order_id: Optional[int] = None
    item_id: int
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    stock_batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    warehouse_id: Optional[int] = None
    warehouse_name: Optional[str] = None
    reserved_quantity: float
    consumed_quantity: float
    released_quantity: float
    unit: str
    status: MaterialReservationStatus
    reservation_type: MaterialReservationType
    source: MaterialReservationSource
    reserved_by: Optional[int] = None
    reserved_at: datetime
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReservationBatchSuggestion(BaseModel):
    stock_batch_id: int
    batch_no: str
    warehouse_id: int
    received_date: datetime
    current_quantity: float
    reserved_quantity: float
    available_quantity: float
    suggested_quantity: float
    unit: str


class MaterialReservationPlanRow(BaseModel):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: Optional[str] = None
    composition: list[ItemComposition] = Field(default_factory=list)
    category: str
    reservation_type: MaterialReservationType
    unit: str
    stock_batch_id: Optional[int] = None
    stock_batch_no: Optional[str] = None
    stock_batch_image_url: Optional[str] = None
    stock_batch_color: Optional[str] = None
    required_quantity: float
    already_reserved_quantity: float
    remaining_to_reserve: float
    current_stock: float
    reserved_stock: float
    available_stock: float
    shortage: float
    suggested_batches: list[ReservationBatchSuggestion] = []
    status: str


class MaterialReservationPlanOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    production_order_id: int
    production_no: str
    order_no: Optional[str] = None
    sales_order_id: Optional[int] = None
    model_id: int
    model_code: Optional[str] = None
    model_name: Optional[str] = None
    planned_quantity: int
    status: str
    is_complete: bool
    warning: Optional[str] = None
    summary: dict
    rows: list[MaterialReservationPlanRow]


class MaterialReservationStatusOut(BaseModel):
    plan: MaterialReservationPlanOut
    summary: dict
    reservations: list[MaterialReservationOut]
