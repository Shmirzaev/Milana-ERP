from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import joinedload, selectinload

from app.core.deps import CurrentUser, DbSession
from app.models import Item, ModelBOM, StockBatch
from app.models.catalog import Model, ModelImage, ModelSize
from app.models.price_calculation import PriceCalculationRequest
from app.schemas.price_calculation import (
    PriceCalculationAccessoriesIn,
    PriceCalculationCreateIn,
    PriceCalculationCuttingIn,
    PriceCalculationFinanceIn,
    PriceCalculationPurchasingIn,
    PriceCalculationRequestOut,
)
from app.services.audit import log_action
from app.services.price_calculation import (
    attach_completed_selling_price,
    can_view_price_requests,
    create_price_request,
    cutting_status,
    is_accessory_pricing_user,
    is_finance_pricing_user,
    is_cutting_pricing_user,
    is_price_purchaser,
    is_sales_pricing_user,
    accessories_status,
    purchasing_status,
    serialize_price_request,
    update_accessories,
    update_cutting_details,
    update_purchasing_details,
)


router = APIRouter(prefix="/price-calculation", tags=["price_calculation"])


def _list_request_load_options():
    return (
        joinedload(PriceCalculationRequest.model).options(
            selectinload(Model.sizes).load_only(ModelSize.id, ModelSize.model_id, ModelSize.size),
            selectinload(Model.images).load_only(
                ModelImage.id,
                ModelImage.model_id,
                ModelImage.file_url,
                ModelImage.file_name,
                ModelImage.content_type,
                ModelImage.image_type,
                ModelImage.is_primary,
            ),
            selectinload(Model.bom)
            .load_only(
                ModelBOM.id,
                ModelBOM.model_id,
                ModelBOM.item_id,
                ModelBOM.stock_batch_id,
                ModelBOM.photo_url,
            )
            .options(
                joinedload(ModelBOM.item).load_only(Item.id, Item.category, Item.image_url),
                joinedload(ModelBOM.stock_batch).load_only(StockBatch.id, StockBatch.image_url),
            ),
        ),
        joinedload(PriceCalculationRequest.cutting_passport),
    )


def _request_or_404(db: DbSession, request_id: int) -> PriceCalculationRequest:
    request = (
        db.query(PriceCalculationRequest)
        .options(
            joinedload(PriceCalculationRequest.model),
            joinedload(PriceCalculationRequest.cutting_passport),
        )
        .filter(PriceCalculationRequest.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(404, "Price calculation request not found")
    return request


@router.get("/requests", response_model=list[PriceCalculationRequestOut])
def list_requests(db: DbSession, current: CurrentUser):
    if not can_view_price_requests(current):
        raise HTTPException(403, "Price calculation access required")
    requests = (
        db.query(PriceCalculationRequest)
        .options(*_list_request_load_options())
        .order_by(PriceCalculationRequest.id.desc())
        .all()
    )
    return [serialize_price_request(request) for request in requests]


@router.post("/requests", response_model=PriceCalculationRequestOut, status_code=201)
def create_request(payload: PriceCalculationCreateIn, db: DbSession, current: CurrentUser):
    if not is_sales_pricing_user(current):
        raise HTTPException(403, "Sales access required")
    request = create_price_request(db, payload.model_id, current)
    db.commit()
    db.refresh(request)
    return serialize_price_request(request)


@router.patch("/requests/{request_id}/cutting", response_model=PriceCalculationRequestOut)
def update_cutting(request_id: int, payload: PriceCalculationCuttingIn, db: DbSession, current: CurrentUser):
    if not is_cutting_pricing_user(current):
        raise HTTPException(403, "Cutting price calculation access required")
    request = _request_or_404(db, request_id)
    update_cutting_details(db, request, payload.model_dump(), current)
    db.commit()
    db.refresh(request)
    return serialize_price_request(request)


@router.patch("/requests/{request_id}/finance", response_model=PriceCalculationRequestOut)
def update_finance(request_id: int, payload: PriceCalculationFinanceIn, db: DbSession, current: CurrentUser):
    if not is_finance_pricing_user(current):
        raise HTTPException(403, "Finance access required")
    request = _request_or_404(db, request_id)
    changes = payload.model_dump(exclude_unset=True)
    if (
        changes.get("selling_price") is not None
        and changes["selling_price"] > 0
        and (cutting_status(request) != "complete" or purchasing_status(request) != "complete" or accessories_status(request) != "complete")
    ):
        raise HTTPException(409, "Cost details must be completed before entering the selling price")
    old_value = {key: getattr(request, key) for key in changes}
    for key, value in changes.items():
        setattr(request, key, value)
    request.finance_updated_by_id = current.id
    log_action(db, current, "update_finance_price", "PriceCalculationRequest", request.id, old_value=old_value, new_value=changes)
    db.flush()
    attach_completed_selling_price(db, request, current)
    db.commit()
    db.refresh(request)
    return serialize_price_request(request)


@router.patch("/requests/{request_id}/purchasing", response_model=PriceCalculationRequestOut)
def update_purchasing(request_id: int, payload: PriceCalculationPurchasingIn, db: DbSession, current: CurrentUser):
    if not is_price_purchaser(current):
        raise HTTPException(403, "Abbosbek purchasing access required")
    request = _request_or_404(db, request_id)
    update_purchasing_details(db, request, payload.model_dump(), current)
    db.commit()
    db.refresh(request)
    return serialize_price_request(request)


@router.patch("/requests/{request_id}/accessories", response_model=PriceCalculationRequestOut)
def update_request_accessories(request_id: int, payload: PriceCalculationAccessoriesIn, db: DbSession, current: CurrentUser):
    if not is_accessory_pricing_user(current):
        raise HTTPException(403, "Accessory team access required")
    request = _request_or_404(db, request_id)
    update_accessories(db, request, [row.model_dump() for row in payload.accessories], current)
    db.commit()
    db.refresh(request)
    return serialize_price_request(request)
