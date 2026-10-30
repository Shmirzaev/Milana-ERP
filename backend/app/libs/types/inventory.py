"""Internal Inventory operation commands."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, NotRequired, TypedDict

from app.libs.enums.inventory import FabricScanDepartment, FabricScanDirection, StockBatchQcStatus

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


class StockBatchEditValues(TypedDict, total=False):
    """Explicit nullable patch for mapped StockBatch fields; absent means keep."""

    item_id: NotRequired[int]
    batch_no: NotRequired[str | None]
    supplier_id: NotRequired[int | None]
    color: NotRequired[str | None]
    old_code: NotRequired[str | None]
    color_code: NotRequired[str | None]
    color_status: NotRequired[str | None]
    order_no: NotRequired[str | None]
    width: NotRequired[float | None]
    length_m: NotRequired[float | None]
    gsm: NotRequired[float | None]
    quantity: NotRequired[float | None]
    piece_count: NotRequired[int | None]
    processes: NotRequired[str | None]
    unit: NotRequired[str | None]
    cost_per_unit: NotRequired[Decimal | None]
    image_url: NotRequired[str | None]
    received_date: NotRequired[datetime | None]
    warehouse_id: NotRequired[int | None]
    qc_status: NotRequired[StockBatchQcStatus | None]


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

    values: StockBatchEditValues
    old_warehouse_id: int
    target_warehouse_id: int
    target_quantity: float
    old_quantity: float
    target_unit: str
    actor_id: int
    relink_item_id: int | None = None
    item_movements: tuple["StockMovement", ...] = ()


@dataclass(frozen=True)
class PurchaseOrderStockReceiptCommand:
    """Normalized stock write requested by Purchasing on one Session.

    Purchasing owns validation and the outer receipt transaction. Inventory
    owns the batch and movement construction; this command crosses that public
    participant boundary without exposing the HTTP DTO or ORM rows.
    """

    item_id: int
    batch_no: str
    internal_batch_no: str
    supplier_id: int | None
    color: str | None
    old_code: str | None
    color_code: str | None
    color_status: str | None
    order_no: str | None
    width: float | None
    gsm: float | None
    quantity: float
    piece_count: int | None
    roll_weights_kg: list[float]
    processes: str | None
    unit: str
    cost_per_unit: Decimal
    image_url: str | None
    warehouse_id: int
    qc_status: StockBatchQcStatus
    purchase_order_line_id: int
    created_by: int | None


@dataclass(frozen=True)
class PurchaseOrderStockReceiptResult:
    """Flushed Inventory facts needed by Purchasing's existing audit payload."""

    batch_id: int
    batch_no: str
    internal_batch_no: str | None
