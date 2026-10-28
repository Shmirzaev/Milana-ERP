from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.libs.enums.planning import ForecastRecommendationType

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
        gt=Decimal("0"),
        le=Decimal("9999999999.9999"),
        allow_inf_nan=False,
    )
    unit: str | None = None
    confidence: str | None = None
    reason: str | None = None
    source_json: dict[str, Any] | None = None
