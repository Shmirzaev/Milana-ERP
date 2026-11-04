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


def apply_finance_contribution(
    db: Session, request: PriceCalculationRequest, changes: dict[str, float | None], *, updated_by_id: int
) -> None:
    """Apply supplied fields; the caller retains audit and flush order."""
    for field, value in changes.items():
        setattr(request, field, value)
    request.finance_updated_by_id = updated_by_id
