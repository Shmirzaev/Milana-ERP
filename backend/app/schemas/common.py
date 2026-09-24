from decimal import Decimal, InvalidOperation
from typing import Generic, TypeVar, Optional
from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


def reject_cost_fractional_precision(value: object, *, minimum: Decimal) -> object:
    """Reject a new cost that Numeric(12,4) would silently round.

    Leave nonnumeric and out-of-range inputs to their existing field validators.
    The original value is returned so the public float input contract remains.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if not amount.is_finite() or not minimum <= amount <= Decimal("99999999.9999"):
        return value
    digits = amount.as_tuple().digits
    exponent = amount.as_tuple().exponent
    extra_places = -exponent - 4
    if extra_places > 0 and any(digits[-extra_places:]):
        raise ValueError("Cost per unit cannot have more than 4 decimal places")
    return value


class SchemaModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class ORMModel(SchemaModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = 50


class MessageOut(SchemaModel):
    message: str
    detail: Optional[str] = None
