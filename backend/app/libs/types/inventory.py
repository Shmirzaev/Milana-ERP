"""Internal Inventory operation commands."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from app.schemas import StockBatch

from app.libs.enums.inventory import (
    FabricScanDepartment, FabricScanDirection, MaterialReservationType,
    ReservationPlanRowStatus, ReservationPlanStatus,
)


@dataclass(frozen=True)
class FabricScanCreateCommand:
    """Server-owned scan snapshot passed from the operation to its writer."""

    department: FabricScanDepartment
    report_date: date
    batch_id: int
    roll_number: int
    direction: FabricScanDirection
    fabric_name: str
    batch_no: str
    color: str | None
    operator_id: int
    operator_name: str
    scanned_at: datetime


class ItemCompositionValue(TypedDict):
    name: str
    percentage: float


@dataclass(frozen=True)
class ItemInsertCommand:
    """Normalized Item values after the service's existing create checks."""

    sku: str
    name: str
    category: str
    unit: str
    default_cost: Decimal
    reorder_level: Decimal
    track_batch: bool
    is_active: bool
    image_url: str | None
    composition_json: list[ItemCompositionValue]


class ReservationRequirement(TypedDict):
    item_id: int
    item_sku: str
    item_name: str
    item_image_url: str | None
    composition: list[ItemCompositionValue]
    category: str
    reservation_type: MaterialReservationType
    unit: str
    stock_batch_id: int | None
    stock_batch_no: str | None
    stock_batch_image_url: str | None
    stock_batch_color: str | None
    required_quantity: float


class ReservationBatchSuggestionValue(TypedDict):
    stock_batch_id: int
    batch_no: str
    warehouse_id: int
    received_date: datetime
    current_quantity: float
    reserved_quantity: float
    available_quantity: float
    suggested_quantity: float
    unit: str


class ReservationPlanRow(ReservationRequirement):
    already_reserved_quantity: float
    remaining_to_reserve: float
    current_stock: float
    reserved_stock: float
    available_stock: float
    shortage: float
    suggested_batches: list[ReservationBatchSuggestionValue]
    status: ReservationPlanRowStatus


class ReservationPlanSummary(TypedDict):
    # sum() returns integer zero when there are no rows.
    required_quantity: int | float
    already_reserved_quantity: int | float
    remaining_to_reserve: int | float
    shortage: int | float
    line_count: int
    ready_line_count: int
    shortage_line_count: int


class ReservationPlanStockContext(TypedDict):
    current_by_item: dict[int, float]
    reserved_by_item: dict[int, float]
    reserved_by_batch: dict[int, float]
    candidates_by_item: dict[int, list["StockBatch"]]
    candidate_ids: dict[int, "StockBatch"]
    batches_by_id: dict[int, "StockBatch"]


class ReservationPlan(TypedDict):
    production_order_id: int
    production_no: str
    order_no: str | None
    sales_order_id: int | None
    model_id: int
    model_code: str | None
    model_name: str | None
    planned_quantity: int
    status: ReservationPlanStatus
    is_complete: bool
    warning: str | None
    summary: ReservationPlanSummary
    rows: list[ReservationPlanRow]
