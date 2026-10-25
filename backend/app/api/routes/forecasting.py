from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import DbSession, factory_codes_with_permission, require_permissions
from app.libs.dto.planning.forecast_recommendation_input import ForecastRecommendationIn
from app.libs.dto.planning.forecast_recommendation_output import ForecastRecommendationOut
from app.libs.dto.planning.forecast_recommendation_update import ForecastRecommendationPatch
from app.models.forecasting_service import (
    branded_stock_suggestions,
    forecasting_dashboard,
    item_reorder_suggestions,
)
from app.models.planning import forecasting_recommendations_service
from app.schemas import User

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


@router.get("/dashboard")
def get_forecasting_dashboard(
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.view", "*")),
):
    return forecasting_dashboard(db, factory_codes=factory_codes_with_permission(current, "forecasting.view"))


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
    return forecasting_recommendations_service.create_recommendation(
        db,
        payload,
        factory_codes_with_permission(current, "forecasting.manage"),
        current,
    )


@router.get("/recommendations", response_model=list[ForecastRecommendationOut])
def list_forecast_recommendations(
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.view", "*")),
    status: str | None = None,
):
    return forecasting_recommendations_service.list_recommendations(
        db,
        factory_codes_with_permission(current, "forecasting.view"),
        status,
    )


@router.patch("/recommendations/{recommendation_id}", response_model=ForecastRecommendationOut)
def update_forecast_recommendation(
    recommendation_id: int,
    payload: ForecastRecommendationPatch,
    db: DbSession,
    current: User = Depends(require_permissions("forecasting.manage", "*")),
):
    return forecasting_recommendations_service.update_recommendation(
        db,
        recommendation_id,
        payload,
        factory_codes_with_permission(current, "forecasting.manage"),
        current,
    )
