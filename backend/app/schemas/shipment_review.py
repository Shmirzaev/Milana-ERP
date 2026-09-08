from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ShipmentTransportDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    driver_name: str | None = Field(default=None, max_length=200)
    vehicle_info: str | None = Field(default=None, max_length=200)
    cargo_name: str | None = Field(default=None, max_length=200)
    driver_phone: str | None = Field(default=None, max_length=50)

    @field_validator("driver_name", "vehicle_info", "cargo_name", "driver_phone")
    @classmethod
    def strip_empty(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ShipmentQuantityLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(gt=0, strict=True)
    quantity: int = Field(ge=0, strict=True)


class ShipmentQuantityReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_quantity: int = Field(gt=0, strict=True)
    reason: str = Field(min_length=3, max_length=1000)
    items: list[ShipmentQuantityLine] = Field(min_length=1, max_length=200)
    confirm_extra_receipt: bool = Field(default=False, strict=True)


class ShipmentAmountReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)
    reason: str = Field(min_length=3, max_length=1000)
    basis: str = Field(min_length=64, max_length=64)


class ShipmentPackageRemoval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=1000)
