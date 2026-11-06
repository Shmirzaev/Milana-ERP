from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
