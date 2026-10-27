"""Persisted purchasing states.

These are the stored `purchase_requests.status` and `purchase_orders.status`
strings. The create operations accept only their own creation subset; the
service owns that rule and the remaining lifecycle states.
"""

from enum import Enum


class PurchaseRequestStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED = "converted"


class PurchaseOrderStatus(str, Enum):
    """Stored `purchase_orders.status` values.

    Order creation accepts only `DRAFT` and `SENT`. `APPROVED`,
    `PARTIALLY_RECEIVED` and `RECEIVED` belong to the receiving lifecycle and
    are written by the receipt operation, not by order creation.
    """

    DRAFT = "draft"
    SENT = "sent"
    APPROVED = "approved"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
