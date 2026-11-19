from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

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
from app.models.planning import variant_pricing_service, price_reports_service
from app.libs.enums.catalog import CatalogScope
from app.libs.enums.planning import PriceContributionTeam, PriceRequestQueue, PriceReportFilter
from app.libs.dto.planning.price_workflow_input import PriceWorkflowActionIn, PriceApprovalIn, PriceCorrectionIn, PriceCancelIn, PriceRepriceIn
from app.libs.dto.planning.price_calculation_request_output import VariantPriceReportOut


router = APIRouter(prefix="/price-calculation", tags=["price_calculation"])

PRICE_REQUEST_LIST_LIMIT_MAX = 500
PRICE_REQUEST_LIST_LIMIT_DEFAULT = 50


@router.get("/requests", response_model=list[PriceCalculationRequestOut])
def list_requests(
    db: DbSession,
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=PRICE_REQUEST_LIST_LIMIT_MAX)] = PRICE_REQUEST_LIST_LIMIT_DEFAULT,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    queue: PriceRequestQueue = PriceRequestQueue.ALL,
    team: PriceContributionTeam | None = None,
    q: Annotated[str, Query(max_length=128)] = "",
    catalog_scope: CatalogScope = CatalogScope.STANDARD,
):
    return costing_service.list_price_requests(db, current, limit, before_id, queue, team, q, catalog_scope)


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


@router.post("/requests/{request_id}/submit/{team}", response_model=PriceCalculationRequestOut)
def submit_costs(request_id: int, team: PriceContributionTeam, payload: PriceWorkflowActionIn, db: DbSession, current: CurrentUser):
    return variant_pricing_service.submit_contribution(db, request_id, team, payload, current)


@router.post("/requests/{request_id}/approve", response_model=PriceCalculationRequestOut)
def approve_price(request_id: int, payload: PriceApprovalIn, db: DbSession, current: CurrentUser):
    return variant_pricing_service.approve(db, request_id, payload, current)


@router.post("/requests/{request_id}/return", response_model=PriceCalculationRequestOut)
def return_price(request_id: int, payload: PriceCorrectionIn, db: DbSession, current: CurrentUser):
    return variant_pricing_service.return_for_correction(db, request_id, payload, current)


@router.get("/report", response_model=list[VariantPriceReportOut])
def price_report(db: DbSession, current: CurrentUser, status: PriceReportFilter = PriceReportFilter.ALL,
    q: Annotated[str, Query(max_length=128)] = "", catalog_scope: CatalogScope = CatalogScope.STANDARD,
    before_id: Annotated[int | None, Query(ge=1)] = None, limit: Annotated[int, Query(ge=1, le=500)] = 50):
    return price_reports_service.list_prices(db, current, status, q, catalog_scope, before_id, limit)


@router.post("/requests/{request_id}/cancel", response_model=PriceCalculationRequestOut)
def cancel_price(request_id: int, payload: PriceCancelIn, db: DbSession, current: CurrentUser):
    return variant_pricing_service.cancel_request(db, request_id, payload, current)


@router.post("/models/{model_id}/reprice", response_model=PriceCalculationRequestOut)
def request_reprice(model_id: int, payload: PriceRepriceIn, db: DbSession, current: CurrentUser):
    return variant_pricing_service.request_reprice(db, model_id, payload, current)


@router.get("/report.xlsx")
def export_price_report(db: DbSession, current: CurrentUser, status: PriceReportFilter = PriceReportFilter.ALL,
    q: Annotated[str, Query(max_length=128)] = "", catalog_scope: CatalogScope = CatalogScope.STANDARD):
    return Response(price_reports_service.export_prices(db, current, status, q, catalog_scope),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="variant-prices.xlsx"'})


@router.get("/models/{model_id}/history", response_model=list[PriceCalculationRequestOut])
def price_history(model_id: int, db: DbSession, current: CurrentUser):
    return price_reports_service.history(db, current, model_id)
