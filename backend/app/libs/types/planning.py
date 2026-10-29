"""Internal contracts for Planning and costing operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PriceCalculationPurchasingCommand:
    """The two Purchasing contribution values supplied for one price request.

    Both values remain nullable because the existing PATCH operation treats
    omitted fields as ``None`` and clears the corresponding stored value.
    """

    fabric_price: float | None
    sewing_cost: float | None
