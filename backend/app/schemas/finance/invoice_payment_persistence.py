"""Schema-owned persistence for the finance invoice payment operation.

The mapped `Invoice` and `Payment` classes stay in `app.schemas.sales.sales`;
they are imported, never redefined, and the mapping metadata is untouched.
This module owns only their mapped construction, insert and field mutation for
the "record an invoice payment" operation.

Business rules stay in the services: the reversed-invoice refusal, the row
lock, money normalization, the USD settlement tolerance, authorization, the
audit and idempotency participants, and the single outer commit.

The helpers use the Session they are given. They never commit, never begin or
nest a transaction, never swallow an error, and never import a service or a
route. The outer business operation owns the transaction.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.finance import InvoiceStatus
from app.schemas.sales.sales import Invoice, Payment


def insert_invoice_payment(
    db: Session,
    *,
    invoice_id: int,
    customer_id: int | None,
    amount: Decimal,
    payment_method: str | None,
    paid_at: datetime,
    notes: str | None,
) -> Payment:
    """Construct, stage and flush one `payments` row bound to an invoice.

    `amount` is already bounded and exact, `paid_at` is already normalized to
    UTC. The columns this operation does not own (`external_source`,
    `external_id`) keep their column defaults and stay unset.
    """
    payment = Payment(
        invoice_id=invoice_id,
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        paid_at=paid_at,
        notes=notes,
    )
    db.add(payment)
    db.flush()
    return payment


def set_invoice_status(invoice: Invoice, status: InvoiceStatus) -> None:
    """Apply the settled status to the mapped invoice row.

    The caller owns the row and the lock on it; only the mapped field changes
    here. The application holds the canonical member and the mapped column
    converts it to the existing raw string at the storage boundary, so the
    stored value is still 'partially_paid'. `str(status)` would produce
    "InvoiceStatus.PAID" and is never used.
    """
    invoice.status = status
