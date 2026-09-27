from decimal import Decimal

from fastapi import HTTPException


MAX_SALES_ORDER_TOTAL = Decimal("999999999999.99")
_SALES_ORDER_TOTAL_OVERFLOW_THRESHOLD = Decimal("999999999999.995")


def validate_sales_order_total(total: Decimal) -> Decimal:
    """Reject totals that would round beyond the NUMERIC(14, 2) maximum."""
    if not total.is_finite() or total < 0 or total >= _SALES_ORDER_TOTAL_OVERFLOW_THRESHOLD:
        raise HTTPException(422, f"Order total exceeds the supported maximum of {MAX_SALES_ORDER_TOTAL}")
    return total
