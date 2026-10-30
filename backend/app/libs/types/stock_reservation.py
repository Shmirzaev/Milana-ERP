"""Sales/Fulfillment contracts used by the approved reservation operations.

Demand objects are immutable. The public service also validates their runtime
contents: dataclass type annotations alone do not enforce an input contract.
"""
from dataclasses import dataclass
from typing import TypedDict


@dataclass(frozen=True)
class PieceDemand:
    model_id: int
    brand_id: int | None
    color: str
    size: str
    quantity: int


@dataclass(frozen=True)
class PackDemand:
    demand_key: str
    model_id: int
    brand_id: int | None
    pack_count: int


class ReservationSummary(TypedDict):
    stock_id: int
    # Existing display identity: None for legacy partial allocations. The stored
    # StockReservation.package_id is written separately and may remain non-null.
    package_id: int | None
    qty: int


class StockShortage(TypedDict):
    model_id: int
    brand_id: int | None
    color: str
    size: str
    shortage: int


@dataclass(frozen=True)
class PieceReservationResult:
    reservations: tuple[ReservationSummary, ...]
    shortages: tuple[StockShortage, ...]


@dataclass(frozen=True)
class PackReservationResult:
    reservations: tuple[ReservationSummary, ...]
    piece_quantities_by_demand: dict[str, int]


@dataclass(frozen=True)
class ManualPackageReservationResult:
    """Saved direct reservation of one complete manual package."""

    stock_id: int
    package_id: int
    quantity: int


@dataclass(frozen=True)
class PieceStockReservationResult:
    """Saved direct piece reservation of one stock row."""

    stock_id: int
    quantity: int


DirectStockReservationResult = ManualPackageReservationResult | PieceStockReservationResult
