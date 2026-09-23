from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import DbSession, require_permissions
from app.models import Brand, Collection, ForecastRecommendation, Item, Model, User
from app.schemas.forecasting import (
    ForecastRecommendationIn,
    ForecastRecommendationOut,
    ForecastRecommendationPageOut,
    ForecastRecommendationPatch,
)
from app.services.audit import log_action
from app.services.forecasting import (
    branded_stock_suggestions,
    forecasting_dashboard,
    item_reorder_suggestions,
)

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


def _recommendation_payload(row: ForecastRecommendation) -> dict:
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
        "source_json": row.source_json,
        "created_by": int(row.created_by) if row.created_by else None,
        "reviewed_by": int(row.reviewed_by) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _validate_recommendation_references(payload: ForecastRecommendationIn, db: DbSession) -> None:
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
        if value is not None and db.query(entity.id).filter(entity.id == value).first() is None:
            raise HTTPException(400, f"{field} references a missing record")


@router.get("/dashboard")
def get_forecasting_dashboard(
    db: DbSession,
    _: object = Depends(require_permissions("forecasting.view", "*")),
):
    return forecasting_dashboard(db)


@router.get("/branded-stock-suggestions")
def get_branded_stock_suggestions(
    db: DbSession,
    _: object = Depends(require_permissions("forecasting.view", "*")),
):
    return branded_stock_suggestions(db)


@router.get("/item-reorder-suggestions")
def get_item_reorder_suggestions(
    db: DbSession,
    _: object = Depends(require_permissions("forecasting.view", "*")),
):
    return item_reorder_suggestions(db)


@router.post("/recommendations", response_model=ForecastRecommendationOut, status_code=201)
def create_forecast_recommendation(
    payload: ForecastRecommendationIn,
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.manage", "*")),
):
    _validate_recommendation_references(payload, db)
    row = ForecastRecommendation(
        recommendation_type=payload.recommendation_type,
        status="open",
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
    db.add(row)
    db.flush()
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
    return _recommendation_payload(row)


@router.get(
    "/recommendations",
    response_model=list[ForecastRecommendationOut] | ForecastRecommendationPageOut,
)
def list_forecast_recommendations(
    db: DbSession,
    _: object = Depends(require_permissions("forecasting.view", "*")),
    status: str | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    qry = db.query(ForecastRecommendation)
    if status:
        qry = qry.filter(ForecastRecommendation.status == status)
    ordered_qry = qry.order_by(ForecastRecommendation.id.desc())
    if page is None and page_size is None:
        rows = ordered_qry.limit(500).all()
        return [_recommendation_payload(row) for row in rows]

    page = page or 1
    page_size = page_size or 50
    total = qry.order_by(None).count()
    rows = ordered_qry.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "rows": [_recommendation_payload(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.patch("/recommendations/{recommendation_id}", response_model=ForecastRecommendationOut)
def update_forecast_recommendation(
    recommendation_id: int,
    payload: ForecastRecommendationPatch,
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.manage", "*")),
):
    row = db.get(ForecastRecommendation, recommendation_id)
    if not row:
        raise HTTPException(404, "Forecast recommendation not found")
    old_value = {"status": row.status}
    row.status = payload.status
    row.reviewed_by = current.id
    row.reviewed_at = datetime.now(timezone.utc)
    log_action(
        db,
        current,
        f"{payload.status}_forecast_recommendation",
        "ForecastRecommendation",
        row.id,
        old_value=old_value,
        new_value={"status": row.status},
    )
    db.commit()
    db.refresh(row)
    return _recommendation_payload(row)
