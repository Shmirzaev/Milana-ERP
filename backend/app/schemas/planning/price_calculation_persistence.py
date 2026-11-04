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


def set_cutting_passport_reference(request: PriceCalculationRequest, kroy_no: str, passport_id: int | None) -> None:
    """Set the reference before the service resolves passport sizes."""
    request.kroy_no = kroy_no
    request.cutting_passport_id = passport_id


def set_cutting_dimensions(request: PriceCalculationRequest, *, fabric_width_m: Decimal | float | None, lay_length_m: Decimal | float | None) -> None:
    request.fabric_width_m = fabric_width_m
    request.lay_length_m = lay_length_m


def apply_cutting_contribution(
    db: Session, request: PriceCalculationRequest, *,
    size_count: int | None, gramage: Decimal | float | None, binding_kg_per_piece: Decimal | float | None,
) -> None:
    """Apply resolved values and flush in the caller's transaction."""
    request.size_count = size_count
    request.gramage = gramage
    request.binding_kg_per_piece = binding_kg_per_piece
    db.flush()
