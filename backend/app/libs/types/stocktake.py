"""Partial snapshot evidence: old JSON may omit keys or contain legacy strings."""
from typing import TypedDict


class StocktakeItemSnapshot(TypedDict, total=False):
    model_code: str | None
    model_name: str | None
    color: str | None
    size: str | None
    quantity: int


class StocktakeSnapshot(TypedDict, total=False):
    package_no: str | None
    barcode: str | None
    model_code: str | None
    model_name: str | None
    color: str | None
    quantity: int
    available: int
    reserved: int
    status: str
    warehouse_id: int | None
    location: str
    items: list[StocktakeItemSnapshot]
