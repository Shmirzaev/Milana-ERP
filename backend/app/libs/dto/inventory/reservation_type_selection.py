"""Private states for deferred reservation-type validation."""

from enum import Enum

from app.libs.enums.inventory import MaterialReservationType


class DeferredReservationType(Enum):
    FALLBACK = "fallback"
    INVALID = "invalid"


def reservation_type_selection(value: object) -> MaterialReservationType | DeferredReservationType:
    if isinstance(value, (MaterialReservationType, DeferredReservationType)):
        return value
    if not value:
        return DeferredReservationType.FALLBACK
    try:
        return MaterialReservationType(str(value).strip())
    except ValueError:
        return DeferredReservationType.INVALID
