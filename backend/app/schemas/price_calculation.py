from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _reject_storage_fractional_precision(
    value: object, *, places: int, maximum: Decimal, field_name: str,
) -> object:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if not amount.is_finite() or not Decimal("0") <= amount <= maximum:
        return value
    digits = amount.as_tuple().digits
    extra_places = -amount.as_tuple().exponent - places
    if extra_places > 0 and any(digits[-extra_places:]):
        raise ValueError(f"{field_name} cannot have more than {places} decimal places")
    return value


class PriceCalculationCreateIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="forbid")
    model_id: int = Field(gt=0)


class PriceCalculationFinanceIn(BaseModel):
    cost_price_uzs: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("9999999999999999.99"),
        allow_inf_nan=False,
    )
    selling_price: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    profit_percentage: float | None = Field(
        default=None, ge=0, le=999_999.99, allow_inf_nan=False,
    )
    exchange_rate: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )

    @field_validator("cost_price_uzs", "selling_price", "profit_percentage", "exchange_rate", mode="before")
    @classmethod
    def reject_fractional_precision(cls, value: object, info: ValidationInfo) -> object:
        places, maximum = {
            "cost_price_uzs": (2, Decimal("9999999999999999.99")),
            "selling_price": (4, Decimal("9999999999.9999")),
            "profit_percentage": (2, Decimal("999999.99")),
            "exchange_rate": (4, Decimal("9999999999.9999")),
        }[info.field_name]
        return _reject_storage_fractional_precision(
            value, places=places, maximum=maximum, field_name=info.field_name,
        )


class PriceCalculationPurchasingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fabric_price: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    sewing_cost: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )

    @field_validator("fabric_price", "sewing_cost", mode="before")
    @classmethod
    def reject_fractional_precision(cls, value: object, info: ValidationInfo) -> object:
        return _reject_storage_fractional_precision(
            value, places=4, maximum=Decimal("9999999999.9999"), field_name=info.field_name,
        )


class PriceCalculationCuttingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kroy_no: str = Field(min_length=1, max_length=32)
    fabric_width_m: float | None = Field(
        default=None, gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    lay_length_m: float | None = Field(
        default=None, gt=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    size_count: int | None = Field(default=None, gt=0, le=2_147_483_647)
    gramage: float | None = Field(
        default=None, gt=0, le=99_999_999.999999, allow_inf_nan=False,
    )
    binding_kg_per_piece: float | None = Field(
        default=None, ge=0, le=99_999_999.999999, allow_inf_nan=False,
    )

    @field_validator(
        "fabric_width_m", "lay_length_m", "gramage", "binding_kg_per_piece", mode="before",
    )
    @classmethod
    def reject_fractional_precision(cls, value: object, info: ValidationInfo) -> object:
        places, maximum = (
            (4, Decimal("9999999999.9999"))
            if info.field_name in {"fabric_width_m", "lay_length_m"}
            else (6, Decimal("99999999.999999"))
        )
        return _reject_storage_fractional_precision(
            value, places=places, maximum=maximum, field_name=info.field_name,
        )

    @field_validator("kroy_no")
    @classmethod
    def clean_kroy_no(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Kroy number is required")
        return cleaned


class PriceCalculationAccessoryIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    price: float | None = Field(default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None


class PriceCalculationAccessoriesIn(BaseModel):
    accessories: list[PriceCalculationAccessoryIn] = Field(default_factory=list, max_length=4)


class PriceCalculationAccessoryOut(BaseModel):
    name: str | None = None
    price: float | None = None


class PriceCalculationRequestOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    id: int
    model_id: int
    model_no: str
    variant_no: str
    model_name: str
    model_category: str | None = None
    model_sizes: list[str] = Field(default_factory=list)
    model_image_url: str | None = None
    variant_image_url: str | None = None
    kroy_no: str | None = None
    cutting_passport_id: int | None = None
    date: datetime | None = None
    fabric_width_m: float | None = None
    lay_length_m: float | None = None
    size_count: int | None = None
    gramage: float | None = None
    binding_kg_per_piece: float | None = None
    fabric_price: float | None = None
    sewing_cost: float | None = None
    packaging_cost: float
    accessories: list[PriceCalculationAccessoryOut] = Field(default_factory=list)
    cost_price_uzs: float | None = None
    selling_price: float | None = None
    variant_selling_price: float | None = None
    variant_selling_price_request_id: int | None = None
    selling_price_attached: bool = False
    profit_percentage: float | None = None
    exchange_rate: float | None = None
    fabric_consumption: float | None = None
    consumption_cost: float | None = None
    binding_price: float | None = None
    cost_price: float | None = None
    difference: float | None = None
    purchasing_status: str
    cutting_status: str
    accessories_status: str
    overall_status: str
    created_at: datetime
    updated_at: datetime


class PriceCalculationRequestPageOut(BaseModel):
    items: list[PriceCalculationRequestOut]
    total: int
    page: int
    page_size: int
    has_more: bool
