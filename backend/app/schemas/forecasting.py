from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ORMModel


RecommendationType = Literal["branded_stock_production", "item_reorder"]
RecommendationStatus = Literal["open", "accepted", "dismissed", "converted"]


class ForecastRecommendationIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    recommendation_type: RecommendationType
    model_id: int | None = None
    item_id: int | None = None
    brand_id: int | None = None
    collection_id: int | None = None
    color: str | None = None
    size: str | None = None
    suggested_quantity: float = Field(gt=0)
    unit: str | None = None
    confidence: str | None = None
    reason: str | None = None
    source_json: dict[str, Any] | None = None


class ForecastRecommendationPatch(BaseModel):
    status: RecommendationStatus


class ForecastRecommendationOut(ORMModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    recommendation_type: str
    status: str
    model_id: int | None = None
    item_id: int | None = None
    brand_id: int | None = None
    collection_id: int | None = None
    color: str | None = None
    size: str | None = None
    suggested_quantity: float
    unit: str | None = None
    confidence: str | None = None
    reason: str | None = None
    source_json: dict[str, Any] | None = None
    created_by: int | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
