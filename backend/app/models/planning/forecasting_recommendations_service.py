"""Forecast recommendations: creation, listing and review.

Contract per operation:
* input: the validated payload, the acting user and the factory scope the user
  may act in
* output: typed creation and review results; legacy listing retains its dictionary payload
* refusals: 400 for a dangling reference, 403 when the recommendation has no
  factory-attributed model or the model is outside the user's factory scope,
  404 when the recommendation does not exist in that scope
* records: one `forecast_recommendations` row and one `ForecastRecommendation`
  audit row
* transaction owner: `create_recommendation` and `update_recommendation`

The read-only forecast calculations stay in `app.models.forecasting_service`.
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.dto.planning.forecast_recommendation_output import (
    ForecastRecommendationCreatedOut, ForecastRecommendationReviewedOut,
)
from app.libs.dto.planning.forecast_recommendation_update import ForecastRecommendationPatch
from app.libs.enums.planning import ForecastRecommendationStatus
from app.models.audit_service import log_action
from app.schemas import Brand, Collection, ForecastRecommendation, Item, Model, User
from app.schemas.planning.forecast_recommendation_persistence import (
    ForecastRecommendationInsert,
    ForecastRecommendationReview,
    apply_forecast_recommendation_review,
    insert_forecast_recommendation,
)


RECOMMENDATION_LIST_LIMIT = 500


def recommendation_payload(row: ForecastRecommendation) -> dict:
    """Return the stored recommendation as a dict."""
    return {
        "id": int(row.id),
        "recommendation_type": row.recommendation_type,
        "status": row.status,
        "model_id": int(row.model_id) if row.model_id else None,
        "item_id": int(row.item_id) if row.item_id else None,
        "brand_id": int(row.brand_id) if row.brand_id else None,
        "collection_id": int(row.collection_id) if row.collection_id else None,
        "color": row.color,
        "size": row.size,
        "suggested_quantity": float(row.suggested_quantity or 0),
        "unit": row.unit,
        "confidence": row.confidence,
        "reason": row.reason,
        "source_json": row.source_json if isinstance(row.source_json, dict) else None,
        "created_by": int(row.created_by) if row.created_by else None,
        "reviewed_by": int(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def validate_recommendation_references(payload: ForecastRecommendationIn, db: Session) -> None:
    """Reject dangling references before creating a recommendation.

    These are existence checks only; visibility and cross-entity business rules
    remain the responsibility of the forecasting policy layer.
    """
    references = (
        ("model_id", Model, payload.model_id),
        ("item_id", Item, payload.item_id),
        ("brand_id", Brand, payload.brand_id),
        ("collection_id", Collection, payload.collection_id),
    )
    for field, entity, value in references:
        if value is not None and db.get(entity, value) is None:
            raise HTTPException(400, f"{field} references a missing record")


def recommendation_query_for_factories(db: Session, factory_codes: list[str]):
    """Return the recommendation query limited to the given factories."""
    return (
        db.query(ForecastRecommendation)
        .join(Model, Model.id == ForecastRecommendation.model_id)
        .filter(Model.factory_code.in_(factory_codes))
    )


def require_recommendation_factory_access(
    model_id: int | None,
    *,
    factory_codes: list[str],
    db: Session,
) -> None:
    """Refuse a recommendation whose model the user may not act on."""
    if model_id is None:
        raise HTTPException(403, "A factory-attributed model is required for this recommendation")
    if not factory_codes or db.query(Model.id).filter(
        Model.id == model_id,
        Model.factory_code.in_(factory_codes),
    ).first() is None:
        raise HTTPException(403, "Not authorized for this recommendation's factory")


def create_recommendation(
    db: Session,
    payload: ForecastRecommendationIn,
    factory_codes: list[str],
    current: User,
) -> ForecastRecommendationCreatedOut:
    """Open one forecast recommendation inside the user's factory scope."""
    validate_recommendation_references(payload, db)
    require_recommendation_factory_access(
        payload.model_id,
        factory_codes=factory_codes,
        db=db,
    )
    command = ForecastRecommendationInsert(
        recommendation_type=payload.recommendation_type,
        status=ForecastRecommendationStatus.OPEN,
        model_id=payload.model_id,
        item_id=payload.item_id,
        brand_id=payload.brand_id,
        collection_id=payload.collection_id,
        color=payload.color,
        size=payload.size,
        suggested_quantity=payload.suggested_quantity,
        unit=payload.unit,
        confidence=payload.confidence,
        reason=payload.reason,
        source_json=payload.source_json,
        created_by=current.id,
    )
    row = insert_forecast_recommendation(db, command)
    # Validate the newly controlled fields before committing. Legacy list/review
    # projection stays separate because historical stored vocabularies are open.
    ForecastRecommendationCreatedOut.model_validate(recommendation_payload(row))
    log_action(
        db,
        current,
        "create_forecast_recommendation",
        "ForecastRecommendation",
        row.id,
        new_value={
            "recommendation_type": row.recommendation_type,
            "suggested_quantity": float(row.suggested_quantity or 0),
        },
    )
    db.commit()
    db.refresh(row)
    return ForecastRecommendationCreatedOut.model_validate(recommendation_payload(row))


def list_recommendations(db: Session, factory_codes: list[str], status: str | None) -> list[dict]:
    """Return the recommendations of the given factories, newest first."""
    qry = recommendation_query_for_factories(db, factory_codes)
    if status:
        qry = qry.filter(ForecastRecommendation.status == status)
    rows = qry.order_by(ForecastRecommendation.id.desc()).limit(RECOMMENDATION_LIST_LIMIT).all()
    return [recommendation_payload(row) for row in rows]


def update_recommendation(
    db: Session,
    recommendation_id: int,
    payload: ForecastRecommendationPatch,
    factory_codes: list[str],
    current: User,
) -> ForecastRecommendationReviewedOut:
    """Review one forecast recommendation inside the user's factory scope."""
    row = recommendation_query_for_factories(db, factory_codes).filter(
        ForecastRecommendation.id == recommendation_id
    ).first()
    if not row:
        raise HTTPException(404, "Forecast recommendation not found")
    old_value = {"status": row.status}
    apply_forecast_recommendation_review(
        db,
        ForecastRecommendationReview(
            status=payload.status,
            reviewed_by=current.id,
            reviewed_at=datetime.now(timezone.utc),
        ),
        row,
    )
    ForecastRecommendationReviewedOut.model_validate(recommendation_payload(row))
    log_action(
        db,
        current,
        f"{payload.status.value}_forecast_recommendation",
        "ForecastRecommendation",
        row.id,
        old_value=old_value,
        new_value={"status": row.status},
    )
    db.commit()
    db.refresh(row)
    return ForecastRecommendationReviewedOut.model_validate(recommendation_payload(row))
