from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.libs.enums.planning import PriceCalculationStatus, PriceWorkflowState, PriceContributionTeam, PriceMaterialUnit
from app.libs.enums.identity import FactoryCode
from app.libs.enums.catalog import CatalogScope


class PriceMaterialOut(BaseModel):
    key: str
    name: str
    unit: PriceMaterialUnit
    consumption: float | None = None
    rate: float | None = None
    cost: float | None = None


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
    order_no: str | None = None
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
    purchasing_status: PriceCalculationStatus
    cutting_status: PriceCalculationStatus
    accessories_status: PriceCalculationStatus
    overall_status: PriceCalculationStatus
    created_at: datetime
    updated_at: datetime
    workflow_state: PriceWorkflowState = PriceWorkflowState.LEGACY
    factory_code: FactoryCode | None = None
    catalog_scope: CatalogScope = CatalogScope.STANDARD
    revision: int = 1
    materials: list[PriceMaterialOut] = Field(default_factory=list)
    purchasing_submitted_at: datetime | None = None
    accessories_submitted_at: datetime | None = None
    no_accessories_reason: str | None = None
    printing_required: bool = False
    printing_cost: float | None = None
    correction_team: PriceContributionTeam | None = None
    correction_reason: str | None = None
    approved_at: datetime | None = None
    approved_by_id: int | None = None
    approved_by_name: str | None = None
    can_approve: bool = False
    margin_percentage: float | None = None
    calculation_issues: list[str] = Field(default_factory=list)


class VariantPriceReportOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_id: int
    model_no: str
    variant_no: str
    model_name: str
    catalog_scope: CatalogScope
    selling_price: float | None = None
    currency: str | None = None
    source: str | None = None
    price_updated_at: datetime | None = None
    request: PriceCalculationRequestOut | None = None
    pending_factory: FactoryCode | None = None
