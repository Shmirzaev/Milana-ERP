from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceCalculationCreateIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), extra="forbid")
    model_id: int = Field(gt=0)


class PriceCalculationFinanceIn(BaseModel):
    cost_price_uzs: float | None = Field(default=None, ge=0)
    selling_price: float | None = Field(default=None, ge=0)
    profit_percentage: float | None = Field(default=None, ge=0)
    exchange_rate: float | None = Field(default=None, ge=0)


class PriceCalculationPurchasingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fabric_price: float | None = Field(default=None, ge=0)
    sewing_cost: float | None = Field(default=None, ge=0)


class PriceCalculationCuttingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kroy_no: str = Field(min_length=1, max_length=32)
    fabric_width_m: float | None = Field(default=None, gt=0)
    lay_length_m: float | None = Field(default=None, gt=0)
    size_count: int | None = Field(default=None, gt=0)
    gramage: float | None = Field(default=None, gt=0)
    binding_kg_per_piece: float | None = Field(default=None, ge=0)

    @field_validator("kroy_no")
    @classmethod
    def clean_kroy_no(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Kroy number is required")
        return cleaned


class PriceCalculationAccessoryIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    price: float | None = Field(default=None, ge=0)

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
