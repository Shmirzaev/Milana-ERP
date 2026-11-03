"""Internal Inventory operation commands."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from app.libs.enums.inventory import FabricScanDepartment, FabricScanDirection


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
