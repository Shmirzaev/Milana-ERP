"""Forecast creation and review writes using the business service's supplied Session."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.libs.enums.planning import ForecastRecommendationStatus, ForecastRecommendationType
from app.schemas.planning.forecasting import ForecastRecommendation


@dataclass(frozen=True)
class ForecastRecommendationInsert:
    recommendation_type: ForecastRecommendationType
    status: ForecastRecommendationStatus
    model_id: int | None
    item_id: int | None
    brand_id: int | None
    collection_id: int | None
    color: str | None
    size: str | None
    suggested_quantity: Decimal
    unit: str | None
    confidence: str | None
    reason: str | None
    source_json: dict[str, Any] | None
    created_by: int


def insert_forecast_recommendation(
    db: Session, command: ForecastRecommendationInsert,
) -> ForecastRecommendation:
    """Construct/add/flush only; the service owns policy, audit and commit."""
    row = ForecastRecommendation(
        recommendation_type=command.recommendation_type.value,
        status=command.status.value,
        model_id=command.model_id,
        item_id=command.item_id,
        brand_id=command.brand_id,
        collection_id=command.collection_id,
        color=command.color,
        size=command.size,
        suggested_quantity=command.suggested_quantity,
        unit=command.unit,
        confidence=command.confidence,
        reason=command.reason,
        source_json=command.source_json,
        created_by=command.created_by,
    )
    db.add(row)
    db.flush()
    return row


@dataclass(frozen=True)
class ForecastRecommendationReview:
    status: ForecastRecommendationStatus
    reviewed_by: int
    reviewed_at: datetime


def apply_forecast_recommendation_review(
    db: Session,
    command: ForecastRecommendationReview,
    row: ForecastRecommendation,
) -> ForecastRecommendation:
    """Apply the mapped review writes; the service owns policy, audit and commit."""
    row.status = command.status.value
    row.reviewed_by = command.reviewed_by
    row.reviewed_at = command.reviewed_at
    db.flush()
    return row
