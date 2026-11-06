"""Input contracts for the branded planning order feature.

`ordered_for_type` is a fixed business vocabulary, so the field carries the
canonical enum annotation instead of a free-form string. Normalization that the
business service used to do inline (strip, lower-case, then match) is kept here
as an explicit validator, so padded and mixed-case input still resolves to the
same stored value while empty, null and unknown values are refused at the
contract boundary.

The `status` filter is a query contract, not a body contract, so it does not
inherit that normalization. See `normalize_optional_branded_status`.
"""
from typing import Annotated, Optional

from pydantic import BeforeValidator

from app.libs.dto.common import SchemaModel
from app.libs.enums.planning import BrandedPlanningOrderStatus, BrandedPlanningOrderType


def normalize_ordered_for_type(value: object) -> BrandedPlanningOrderType:
    """Resolve one ordered-for type to its canonical enum member."""
    if isinstance(value, BrandedPlanningOrderType):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        try:
            return BrandedPlanningOrderType(text)
        except ValueError:
            raise ValueError(
                "ordered_for_type must be one of: "
                + ", ".join(member.value for member in BrandedPlanningOrderType)
            ) from None
    raise ValueError("ordered_for_type must be a string")


def normalize_optional_branded_status(value: object) -> BrandedPlanningOrderStatus | None:
    """Resolve one branded planning order status filter to its canonical member.

    The list query is a different contract from the create body, so it keeps the
    old query semantics instead of the body's normalization:

    * an omitted parameter keeps the caller's ``open`` default;
    * an explicit empty parameter (``?status=``) is the old "no filter" sentinel
      and selects every status;
    * any other value must be exactly a canonical status. Upper-case or padded
      input used to match no row, so it is refused (422) rather than turned into
      a new matching alias.
    """
    if value is None:
        return None
    if isinstance(value, BrandedPlanningOrderStatus):
        return value
    if isinstance(value, str):
        if value == "":
            return None
        try:
            return BrandedPlanningOrderStatus(value)
        except ValueError:
            raise ValueError(
                "status must be one of: "
                + ", ".join(member.value for member in BrandedPlanningOrderStatus)
            ) from None
    raise ValueError("status must be a string")


OrderedForType = Annotated[BrandedPlanningOrderType, BeforeValidator(normalize_ordered_for_type)]
BrandedStatusFilter = Annotated[
    BrandedPlanningOrderStatus | None,
    BeforeValidator(normalize_optional_branded_status),
]


class BrandedPlanningOrderIn(SchemaModel):
    ordered_for_type: OrderedForType = BrandedPlanningOrderType.MILANA
    customer_id: Optional[int] = None
    notes: Optional[str] = None
