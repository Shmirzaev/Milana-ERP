"""Persisted planning vocabulary owned by the planning group.

`BrandedPlanningOrderStatus` and `BrandedPlanningOrderType` are the values of
the `ck_branded_planning_orders_status` and
`ck_branded_planning_orders_ordered_for_type` CHECK constraints on the
`branded_planning_orders` table.

The values are the existing API and storage strings. The columns stay `String`
and no database change is implied. Membership in an enum says nothing about
whether an operation may accept a value: every operation keeps its own
accepted subset.
"""

from enum import Enum


class BrandedPlanningOrderStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class BrandedPlanningOrderType(str, Enum):
    CUSTOMER = "customer"
    MILANA = "milana"
    ECO_COTTON = "eco_cotton"
    BESTTEX = "besttex"


class BrandedCuttingProgress(str, Enum):
    """The derived cutting progress of a branded planning order.

    This is a computed output projection, not a stored work-order status: the
    Planning service aggregates the cutting work orders of a production into
    one of these three states, and a parent order aggregates its productions.
    The serialized strings are unchanged and no database object is involved.
    """

    NOT_STARTED = "not_started"
    PARTIAL = "partial"
    COMPLETED = "completed"
