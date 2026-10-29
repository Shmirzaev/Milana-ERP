"""Internal Inventory operation commands."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from app.libs.enums.inventory import FabricScanDepartment, FabricScanDirection

if TYPE_CHECKING:
    from app.schemas.inventory.inventory import StockMovement


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


@dataclass(frozen=True)
class StockBatchEditCommand:
    """Validated batch-field patch and ledger effects for one batch edit."""

    values: dict[str, object]
    old_warehouse_id: int
    target_warehouse_id: int
    target_quantity: float
    old_quantity: float
    target_unit: str
    actor_id: int
    relink_item_id: int | None = None
    item_movements: tuple["StockMovement", ...] = ()
