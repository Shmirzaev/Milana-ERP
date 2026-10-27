from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.libs.enums.planning import ForecastRecommendationType

# `forecast_recommendations.suggested_quantity` is Numeric(14,4). PostgreSQL
# rounds to four decimals, so 0.00005 is the smallest accepted quantity that
# still stores a positive value; anything below it rounds to zero, a quantity
# this contract refuses to accept in the first place.
STORAGE_MIN_POSITIVE_QUANTITY = Decimal("0.00005")


class ForecastRecommendationIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    recommendation_type: ForecastRecommendationType
    model_id: int | None = None
    item_id: int | None = None
    brand_id: int | None = None
    collection_id: int | None = None
    color: str | None = None
    size: str | None = None
    suggested_quantity: Decimal = Field(
        ge=STORAGE_MIN_POSITIVE_QUANTITY,
        le=Decimal("9999999999.9999"),
        allow_inf_nan=False,
    )
    unit: str | None = None
    confidence: str | None = None
    reason: str | None = None
    source_json: dict[str, Any] | None = None
