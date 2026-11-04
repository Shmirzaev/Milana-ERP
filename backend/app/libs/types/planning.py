"""Internal contracts for Planning and costing operations."""

from dataclasses import dataclass
from typing import Required, TypedDict

from app.libs.enums.planning import ForecastRecommendationType


@dataclass(frozen=True)
class PriceCalculationPurchasingCommand:
    """The two Purchasing contribution values supplied for one price request.

    Both values remain nullable because the existing PATCH operation treats
    omitted fields as ``None`` and clears the corresponding stored value.
    """

    fabric_price: float | None
    sewing_cost: float | None


class ForecastSuggestion(TypedDict, total=False):
    """Generated forecast fields; saved historical recommendations remain unrestricted."""

    recommendation_type: Required[ForecastRecommendationType]
    suggested_quantity: Required[float]
    model_id: int
    model_code: str | None
    model_name: str | None
    brand_id: int | None
    brand_name: str | None
    collection_id: int | None
    collection_name: str | None
    color: str
    size: str
    historical_quantity: int
    historical_order_count: int
    average_weekly_demand: float
    horizon_weeks: int
    projected_demand: int
    available_quantity: float
    pipeline_quantity: int
    unit: str
    confidence: str
    demand_source: str
    is_low_stock: bool
    reason: str
    item_id: int
    item_sku: str
    item_name: str
    category: str | None
    current_quantity: float
    reserved_quantity: float
    reorder_level: float
    planned_bom_demand: float
    recent_usage_90d: float
