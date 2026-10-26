"""Persisted purchase request states.

These are the stored `purchase_requests.status` strings. The create operation
accepts only the `draft` and `pending_approval` subset; the service owns that
rule and the remaining lifecycle states.
"""

from enum import Enum


class PurchaseRequestStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONVERTED = "converted"
