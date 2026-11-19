"""Query contract for the sales-order list status filter."""
from typing import Annotated

from pydantic import BeforeValidator

from app.libs.enums.sales import SalesOrderStatus


def normalize_optional_sales_status(value: object) -> SalesOrderStatus | None:
    """Preserve the empty no-filter sentinel; reject unknown nonempty values."""
    if value is None or value == "":
        return None
    if isinstance(value, SalesOrderStatus):
        return value
    if isinstance(value, str):
        return SalesOrderStatus(value)
    raise ValueError("status must be a string")


SalesStatusFilter = Annotated[
    SalesOrderStatus | None, BeforeValidator(normalize_optional_sales_status)
]
