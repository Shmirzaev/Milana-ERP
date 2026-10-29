"""Typed responses for the daily fabric scan register."""

from datetime import date, datetime

from pydantic import field_serializer

from app.libs.dto.common import SchemaModel
from app.libs.enums.inventory import FabricScanDepartment, FabricScanDirection


class FabricScanRowOut(SchemaModel):
    id: int
    report_date: date
    direction: FabricScanDirection
    fabric_name: str
    batch_no: str
    color: str | None
    roll_number: int
    operator_name: str
    scanned_at: datetime

    @field_serializer("scanned_at", when_used="json")
    def serialize_scanned_at(self, value: datetime) -> str:
        return value.isoformat()


class FabricScanResultOut(SchemaModel):
    duplicate: bool
    row: FabricScanRowOut


class FabricScanSummaryOut(SchemaModel):
    fabric_name: str
    batch_no: str
    color: str | None
    received: int
    returned: int


class FabricScanReportOut(SchemaModel):
    report_date: date
    department: FabricScanDepartment
    total: int
    received: int
    returned: int
    summary: list[FabricScanSummaryOut]
    rows: list[FabricScanRowOut]
    page: int
    page_size: int
