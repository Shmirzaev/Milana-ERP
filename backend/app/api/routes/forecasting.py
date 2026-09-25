from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import DbSession, factory_codes_with_permission, require_permissions
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

_FORECAST_CONFIDENCE_VALUES = frozenset({"low", "medium", "high"})

_MAX_SOURCE_JSON_BYTES = 16 * 1024
_MAX_SOURCE_JSON_DEPTH = 16


def _validate_source_json(source_json: dict | None) -> None:
    """Bound newly submitted provenance before it is persisted as JSON."""
    if source_json is None:
        return

    pending: list[tuple[object, int]] = [(source_json, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, dict):
            if depth > _MAX_SOURCE_JSON_DEPTH:
                raise HTTPException(422, "source_json exceeds the maximum nesting depth")
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if depth > _MAX_SOURCE_JSON_DEPTH:
                raise HTTPException(422, "source_json exceeds the maximum nesting depth")
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise HTTPException(422, "source_json must contain finite numbers")

    try:
        encoded = json.dumps(
            source_json,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise HTTPException(422, "source_json must contain valid JSON values") from exc
    if len(encoded) > _MAX_SOURCE_JSON_BYTES:
        raise HTTPException(422, "source_json exceeds the 16 KiB limit")


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
    """Reject dangling references and contradictory brand/collection links.

    Visibility and other cross-entity business rules remain the responsibility
    of the forecasting policy layer.
    """
    references = (
        ("model_id", Model, payload.model_id),
        ("item_id", Item, payload.item_id),
        ("brand_id", Brand, payload.brand_id),
    )
    for field, entity, value in references:
        if value is not None and db.query(entity.id).filter(entity.id == value).first() is None:
            raise HTTPException(400, f"{field} references a missing record")

    collection_brand_id = None
    if payload.collection_id is not None:
        collection = db.query(Collection.id, Collection.brand_id).filter(
            Collection.id == payload.collection_id
        ).first()
        if collection is None:
            raise HTTPException(400, "collection_id references a missing record")
        collection_brand_id = int(collection.brand_id)

    if (
        payload.brand_id is not None
        and collection_brand_id is not None
        and collection_brand_id != payload.brand_id
    ):
        raise HTTPException(400, "collection_id does not belong to brand_id")


def _recommendation_query_for_factories(db: DbSession, factory_codes: list[str]):
    return (
        db.query(ForecastRecommendation)
        .join(Model, Model.id == ForecastRecommendation.model_id)
        .filter(Model.factory_code.in_(factory_codes))
    )


def _require_recommendation_factory_access(
    model_id: int | None,
    *,
    factory_codes: list[str],
    db: DbSession,
) -> None:
    if model_id is None:
        raise HTTPException(403, "A factory-attributed model is required for this recommendation")
    if not factory_codes or db.query(Model.id).filter(
        Model.id == model_id,
        Model.factory_code.in_(factory_codes),
    ).first() is None:
        raise HTTPException(403, "Not authorized for this recommendation's factory")


@router.get("/dashboard")
def get_forecasting_dashboard(
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.view", "*")),
):
    return forecasting_dashboard(
        db,
        factory_codes=factory_codes_with_permission(current, "forecasting.view"),
    )


@router.get("/branded-stock-suggestions")
def get_branded_stock_suggestions(
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.view", "*")),
):
    return branded_stock_suggestions(
        db,
        factory_codes=factory_codes_with_permission(current, "forecasting.view"),
    )


@router.get("/item-reorder-suggestions")
def get_item_reorder_suggestions(
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.view", "*")),
):
    return item_reorder_suggestions(
        db,
        factory_codes=factory_codes_with_permission(current, "forecasting.view"),
    )


@router.post("/recommendations", response_model=ForecastRecommendationOut, status_code=201)
def create_forecast_recommendation(
    payload: ForecastRecommendationIn,
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.manage", "*")),
):
    _validate_recommendation_references(payload, db)
    if payload.confidence is not None and payload.confidence not in _FORECAST_CONFIDENCE_VALUES:
        raise HTTPException(422, "confidence must be low, medium, or high")
    _validate_source_json(payload.source_json)
    factory_codes = factory_codes_with_permission(current, "forecasting.manage")
    _require_recommendation_factory_access(
        payload.model_id,
        factory_codes=factory_codes,
        db=db,
    )
    unit = payload.unit
    if payload.item_id is not None:
        item_unit = db.query(Item.unit).filter(Item.id == payload.item_id).scalar()
        if unit is not None and unit != item_unit:
            raise HTTPException(409, "Recommendation unit must match the item unit")
        unit = item_unit
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
        unit=unit,
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
    current: User = Depends(require_permissions("forecasting.view", "*")),
    status: str | None = None,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=500)] = None,
):
    qry = db.query(ForecastRecommendation)
    qry = _recommendation_query_for_factories(
        db,
        factory_codes_with_permission(current, "forecasting.view"),
    )
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
    factory_codes = factory_codes_with_permission(current, "forecasting.manage")
    row = _recommendation_query_for_factories(db, factory_codes).filter(
        ForecastRecommendation.id == recommendation_id
    ).first()
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
