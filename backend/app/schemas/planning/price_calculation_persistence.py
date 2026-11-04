"""Schema-owned persistence for Planning price calculation requests."""

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


def apply_accessory_contribution(
    db: Session,
    request: PriceCalculationRequest,
    rows: list[dict],
    *,
    updated_by_id: int,
) -> None:
    """Apply normalized accessory rows and actor in the caller's transaction."""
    request.accessories_json = rows
    request.accessories_updated_by_id = updated_by_id
    db.flush()
