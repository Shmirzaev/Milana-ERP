from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.libs.enums.ceo_dashboard import BalanceStatus, FactoryFilter, ProductionStage, ReportGrouping


class DateBucket(BaseModel):
    start: date
    end: date


@dataclass(frozen=True, slots=True)
class ReportWindow:
    start: date
    end: date
    lower: datetime
    upper: datetime
    as_of: datetime
    factory: FactoryFilter
    grouping: ReportGrouping
    buckets: tuple[DateBucket, ...]


class PackPieces(BaseModel):
    packs: int = Field(default=0, ge=0)
    pieces: int = Field(default=0, ge=0)


class OutputRow(BaseModel):
    factory: str
    department: str
    stage: ProductionStage
    pieces: int = Field(ge=0)


class ActivityBucket(DateBucket):
    output: list[OutputRow] = Field(default_factory=list)
    finished_receipts: PackPieces = Field(default_factory=PackPieces)
    shipments: PackPieces = Field(default_factory=PackPieces)
    receipts_unassigned: PackPieces = Field(default_factory=PackPieces)
    shipments_unassigned: PackPieces = Field(default_factory=PackPieces)
    legacy_imports: PackPieces = Field(default_factory=PackPieces)


class ActivityReport(BaseModel):
    buckets: list[ActivityBucket]


class WaitingRow(BaseModel):
    source: str
    destination: str
    factory: str
    packs: int = Field(default=0, ge=0)
    bundles: int = Field(default=0, ge=0)
    pieces: int = Field(ge=0)
    oldest_since: datetime | None = None


class WarehouseFactoryBalance(PackPieces):
    factory: str
    available_pieces: int = Field(default=0, ge=0)
    reserved_pieces: int = Field(default=0, ge=0)


class WarehouseBalance(PackPieces):
    available_pieces: int = Field(default=0, ge=0)
    reserved_pieces: int = Field(default=0, ge=0)
    by_factory: list[WarehouseFactoryBalance] = Field(default_factory=list)


class MaterialUnitTotal(BaseModel):
    unit: str
    quantity: Decimal = Field(ge=0)
    active_batches: int = Field(ge=0)
    varieties: int = Field(ge=0)


class MaterialBalanceRow(MaterialUnitTotal):
    warehouse: str
    factory: str


class MaterialVarietyRow(BaseModel):
    item: str
    sku: str
    unit: str
    quantity: Decimal = Field(ge=0)
    active_batches: int = Field(ge=0)


class BalanceValues(BaseModel):
    waiting: list[WaitingRow]
    warehouse: WarehouseBalance
    materials: list[MaterialBalanceRow]
    material_totals: list[MaterialUnitTotal]
    material_varieties: list[MaterialVarietyRow] = Field(default_factory=list)


class BalancePoint(DateBucket):
    status: BalanceStatus
    as_of: datetime | None = None
    values: BalanceValues | None = None


class DashboardReport(BaseModel):
    start: date
    end: date
    grouping: ReportGrouping
    factory: FactoryFilter
    timezone: str
    updated_at: datetime
    activity: ActivityReport
    balances: list[BalancePoint]
