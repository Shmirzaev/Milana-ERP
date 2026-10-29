"""Costing: the price calculation request and its department contributions.

Contract per operation:
* input: the validated payload, the request id, the acting user and the list
  bounds
* output: the serialized price calculation request as a dict
* refusals: 403 when the acting user may not use that department, 404 when the
  request does not exist, 409 when a selling price is entered before cutting,
  purchasing and accessories are complete
* records: the request row, its audit row and the department notifications; a
  completed selling price is attached to the model variant
* transaction owner: every operation that writes

The department calculations stay in `app.models.price_calculation_service`; this
module owns the request lifecycle around them.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.planning.price_calculation_request_input import PriceCalculationCreateIn
from app.libs.dto.planning.price_calculation_request_update import (
    PriceCalculationAccessoriesIn,
    PriceCalculationCuttingIn,
    PriceCalculationFinanceIn,
    PriceCalculationPurchasingIn,
)
from app.models import price_calculation_service as pricing
from app.models.audit_service import log_action
from app.schemas import User
from app.schemas.planning.price_calculation import PriceCalculationRequest


def load_price_request(db: Session, request_id: int) -> PriceCalculationRequest:
    """Return the price calculation request with its model assets loaded."""
    request = (
        db.query(PriceCalculationRequest)
        .options(*pricing.price_request_load_options())
        .filter(PriceCalculationRequest.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(404, "Price calculation request not found")
    return request


def list_price_requests(db: Session, current: User, limit: int, before_id: int | None) -> list[dict]:
    """Return the price calculation requests the acting user may see."""
    if not pricing.can_view_price_requests(current):
        raise HTTPException(403, "Price calculation access required")
    qry = (
        db.query(PriceCalculationRequest)
        .options(*pricing.price_request_load_options())
        .order_by(PriceCalculationRequest.id.desc())
    )
    # Seek pagination keeps older rows reachable even when newer requests are
    # inserted between page reads. All five consumers now expose load-more.
    if before_id is not None:
        qry = qry.filter(PriceCalculationRequest.id < before_id)
    return [pricing.serialize_price_request(request) for request in qry.limit(limit).all()]


def create_price_request(db: Session, payload: PriceCalculationCreateIn, current: User) -> dict:
    """Open one price calculation request for a model."""
    if not pricing.is_sales_pricing_user(current):
        raise HTTPException(403, "Sales access required")
    request = pricing.create_price_request(db, payload.model_id, current)
    db.commit()
    db.refresh(request)
    return pricing.serialize_price_request(request)


def update_cutting_details(
    db: Session,
    request_id: int,
    payload: PriceCalculationCuttingIn,
    current: User,
) -> dict:
    """Record the cutting side of a price calculation request."""
    if not pricing.is_cutting_pricing_user(current):
        raise HTTPException(403, "Cutting price calculation access required")
    request = load_price_request(db, request_id)
    pricing.update_cutting_details(db, request, payload.model_dump(), current)
    db.commit()
    db.refresh(request)
    return pricing.serialize_price_request(request)


def update_finance_details(
    db: Session,
    request_id: int,
    payload: PriceCalculationFinanceIn,
    current: User,
) -> dict:
    """Record the finance side of a price calculation request.

    A selling price is only accepted once cutting, purchasing and accessories
    are complete. A completed selling price is attached to the model variant.
    """
    if not pricing.is_finance_pricing_user(current):
        raise HTTPException(403, "Finance access required")
    request = load_price_request(db, request_id)
    changes = payload.model_dump(exclude_unset=True)
    if (
        changes.get("selling_price") is not None
        and changes["selling_price"] > 0
        and (pricing.cutting_status(request) != "complete" or pricing.purchasing_status(request) != "complete" or pricing.accessories_status(request) != "complete")
    ):
        raise HTTPException(409, "Cost details must be completed before entering the selling price")
    old_value = {key: getattr(request, key) for key in changes}
    for key, value in changes.items():
        setattr(request, key, value)
    request.finance_updated_by_id = current.id
    log_action(db, current, "update_finance_price", "PriceCalculationRequest", request.id, old_value=old_value, new_value=changes)
    db.flush()
    pricing.attach_completed_selling_price(db, request, current)
    db.commit()
    db.refresh(request)
    return pricing.serialize_price_request(request)


def update_purchasing_details(
    db: Session,
    request_id: int,
    payload: PriceCalculationPurchasingIn,
    current: User,
) -> dict:
    """Record the purchasing side of a price calculation request."""
    if not pricing.is_price_purchaser(current):
        raise HTTPException(403, "Abbosbek purchasing access required")
    request = load_price_request(db, request_id)
    pricing.update_purchasing_details(db, request, payload.model_dump(), current)
    db.commit()
    db.refresh(request)
    return pricing.serialize_price_request(request)


def update_accessories(
    db: Session,
    request_id: int,
    payload: PriceCalculationAccessoriesIn,
    current: User,
) -> dict:
    """Record the accessory side of a price calculation request."""
    if not pricing.is_accessory_pricing_user(current):
        raise HTTPException(403, "Accessory team access required")
    request = load_price_request(db, request_id)
    pricing.update_accessories(db, request, [row.model_dump() for row in payload.accessories], current)
    db.commit()
    db.refresh(request)
    return pricing.serialize_price_request(request)
