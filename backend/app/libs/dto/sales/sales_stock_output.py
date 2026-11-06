"""Validated public result of Sales' reserve-stock operation and saved replay."""
from pydantic import BaseModel


class SalesStockReservationLineOut(BaseModel):
    stock_id: int
    # Legacy partial allocations keep the existing null display identity.
    package_id: int | None
    qty: int


class SalesStockShortageOut(BaseModel):
    model_id: int
    brand_id: int | None
    color: str
    size: str
    shortage: int


class SalesStockReservationOut(BaseModel):
    reservations: list[SalesStockReservationLineOut]
    shortages: list[SalesStockShortageOut]
