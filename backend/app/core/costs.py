"""Four-decimal storage policy for material and purchasing unit costs."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


UNIT_COST_STEP = Decimal("0.0001")
MAX_UNIT_COST = Decimal("99999999.9999")


def validate_unit_cost(value: object) -> Decimal:
    """Validate the rounded storage range while retaining request precision."""
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise ValueError("Cost must be a finite nonnegative number")
    try:
        cost = Decimal(str(value))
        if not cost.is_finite() or cost < 0:
            raise ValueError("Cost must be a finite nonnegative number")
        if cost >= Decimal("100000000"):
            raise ValueError("Rounded cost must not exceed 99999999.9999")
        rounded = cost.quantize(UNIT_COST_STEP, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Cost must be a finite nonnegative number") from exc
    if rounded > MAX_UNIT_COST:
        raise ValueError("Rounded cost must not exceed 99999999.9999")
    return cost


def round_unit_cost(value: object) -> Decimal:
    return validate_unit_cost(value).quantize(UNIT_COST_STEP, rounding=ROUND_HALF_UP)
