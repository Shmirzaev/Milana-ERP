"""Internal Inventory operation commands."""

from dataclasses import dataclass
from datetime import date, datetime

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
