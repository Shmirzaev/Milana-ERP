from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceCalculationFinanceIn(BaseModel):
    cost_price_uzs: float | None = Field(default=None, ge=0)
    selling_price: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    profit_percentage: float | None = Field(
        default=None, ge=0, le=999_999.99, allow_inf_nan=False,
    )
    exchange_rate: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )


class PriceCalculationPurchasingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fabric_price: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
    )
    sewing_cost: float | None = Field(
        default=None, ge=0, le=9_999_999_999.9999, allow_inf_nan=False,
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

    @field_validator("kroy_no")
    @classmethod
    def clean_kroy_no(cls, value: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise ValueError("Kroy number is required")
        return cleaned


class PriceCalculationAccessoryIn(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None


class PriceCalculationAccessoriesIn(BaseModel):
    accessories: list[PriceCalculationAccessoryIn] = Field(default_factory=list, max_length=4)
