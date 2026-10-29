"""Persisted invoice states shared by finance and its callers.

These are the stored `invoices.status` strings. `ck_invoices_status` and the
column default are derived from them, so the values must not drift apart.
"""

from enum import Enum


class InvoiceStatus(str, Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    VOID = "void"
    CANCELLED = "cancelled"


class CustomerOrderPaymentStatus(str, Enum):
    """Customer-facing payment summary for a sales order's invoice ledger."""

    PAID = "paid"
    PARTIAL = "partial"
    UNPAID = "unpaid"
    NO_INVOICE = "no_invoice"
    VOID = "void"
    CANCELLED = "cancelled"
