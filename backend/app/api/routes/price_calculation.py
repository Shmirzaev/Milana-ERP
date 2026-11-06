from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession
from app.libs.dto.planning.price_calculation_request_input import PriceCalculationCreateIn
from app.libs.dto.planning.price_calculation_request_output import PriceCalculationRequestOut
from app.libs.dto.planning.price_calculation_request_update import (
    PriceCalculationAccessoriesIn,
    PriceCalculationCuttingIn,
    PriceCalculationFinanceIn,
    PriceCalculationPurchasingIn,
)
from app.models.planning import costing_service


router = APIRouter(prefix="/price-calculation", tags=["price_calculation"])

PRICE_REQUEST_LIST_LIMIT_MAX = 500
PRICE_REQUEST_LIST_LIMIT_DEFAULT = 50


@router.get("/requests", response_model=list[PriceCalculationRequestOut])
def list_requests(
    db: DbSession,
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=PRICE_REQUEST_LIST_LIMIT_MAX)] = PRICE_REQUEST_LIST_LIMIT_DEFAULT,
    before_id: Annotated[int | None, Query(ge=1)] = None,
):
    return costing_service.list_price_requests(db, current, limit, before_id)


@router.post("/requests", response_model=PriceCalculationRequestOut, status_code=201)
def create_request(payload: PriceCalculationCreateIn, db: DbSession, current: CurrentUser):
    return costing_service.create_price_request(db, payload, current)


@router.patch("/requests/{request_id}/cutting", response_model=PriceCalculationRequestOut)
def update_cutting(request_id: int, payload: PriceCalculationCuttingIn, db: DbSession, current: CurrentUser):
    return costing_service.update_cutting_details(db, request_id, payload, current)


@router.patch("/requests/{request_id}/finance", response_model=PriceCalculationRequestOut)
def update_finance(request_id: int, payload: PriceCalculationFinanceIn, db: DbSession, current: CurrentUser):
    return costing_service.update_finance_details(db, request_id, payload, current)


@router.patch("/requests/{request_id}/purchasing", response_model=PriceCalculationRequestOut)
def update_purchasing(request_id: int, payload: PriceCalculationPurchasingIn, db: DbSession, current: CurrentUser):
    return costing_service.update_purchasing_details(db, request_id, payload, current)


@router.patch("/requests/{request_id}/accessories", response_model=PriceCalculationRequestOut)
def update_request_accessories(request_id: int, payload: PriceCalculationAccessoriesIn, db: DbSession, current: CurrentUser):
    return costing_service.update_accessories(db, request_id, payload, current)
