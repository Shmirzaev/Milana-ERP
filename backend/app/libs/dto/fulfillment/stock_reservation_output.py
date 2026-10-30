"""Responses for direct finished-goods stock reservation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PieceStockReservationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Literal["reserved"]
    stock_id: int
    quantity: int


class ManualPackageReservationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Literal["reserved"]
    stock_id: int
    quantity: int
    package_id: int


DirectStockReservationOut = ManualPackageReservationOut | PieceStockReservationOut
