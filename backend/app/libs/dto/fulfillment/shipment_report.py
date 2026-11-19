"""Warehouse reporting contracts; no financial or editable shipment fields."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.libs.enums.fulfillment import ShipmentStatus


class ShipmentReportQuery(BaseModel):
    lang: Literal["en", "ru", "uz"] = "en"
    date_from: date | None = None
    date_to: date | None = None
    q: str = Field(default="", max_length=140)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class ShipmentReportPackage(BaseModel):
    package_no: str
    quantity: int


class ShipmentReportRow(BaseModel):
    shipment_id: int
    shipment_no: str
    shipped_at: datetime
    status: ShipmentStatus
    order_no: str
    customer: str
    model: str
    variant: str
    description: str
    color: str
    quantity: int
    packages: list[ShipmentReportPackage]
    sizes: dict[str, int]
    historical_reconstruction: bool


class ShipmentReportOut(BaseModel):
    rows: list[ShipmentReportRow]
    total: int
    quantity: int
    package_count: int
    shipment_count: int
    page: int
    page_size: int
