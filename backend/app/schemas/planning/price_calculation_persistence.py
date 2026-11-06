"""Schema-owned persistence for Planning price calculation requests."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.types.planning import PriceCalculationPurchasingCommand
from app.schemas.planning.price_calculation import PriceCalculationRequest


def apply_purchasing_contribution(
    db: Session,
    request: PriceCalculationRequest,
    command: PriceCalculationPurchasingCommand,
    *,
    updated_by_id: int,
) -> None:
    """Apply and flush Purchasing fields using the caller's Session.

    Authorization, derived status, audit, notifications and commit belong to
    the surrounding business operation.
    """
    request.fabric_price = command.fabric_price
    request.sewing_cost = command.sewing_cost
    request.purchasing_updated_by_id = updated_by_id
    db.flush()


def insert_price_request(
    db: Session, *, model_id: int, created_by_id: int, margin: Decimal | None
) -> PriceCalculationRequest:
    """Insert and flush the request within the caller's transaction."""
    request = PriceCalculationRequest(
        model_id=model_id, created_by_id=created_by_id,
        profit_percentage=margin, accessories_json=[],
    )
    db.add(request)
    db.flush()
    return request
