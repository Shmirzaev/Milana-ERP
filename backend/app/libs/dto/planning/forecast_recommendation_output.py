from datetime import datetime
from typing import Any

from pydantic import ConfigDict

from app.libs.dto.common import ORMModel
from app.libs.enums.planning import ForecastRecommendationStatus, ForecastRecommendationType


class ForecastRecommendationOut(ORMModel):
    """Legacy read/review contract: stored vocabularies remain unconstrained.

    Do not narrow this shared response before reconciling actual stored values.
    Newly created records have the separate canonical contract below.
    """
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


class ForecastRecommendationCreatedOut(ForecastRecommendationOut):
    """Typed result of the controlled creation operation, not a legacy reader."""

    recommendation_type: ForecastRecommendationType
    status: ForecastRecommendationStatus


class ForecastRecommendationReviewedOut(ForecastRecommendationOut):
    """Review controls status but may operate on a historical recommendation type."""

    status: ForecastRecommendationStatus
