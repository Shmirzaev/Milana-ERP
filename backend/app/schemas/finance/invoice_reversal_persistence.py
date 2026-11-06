"""Schema-owned Finance writes for invoice reversal participants."""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.finance import InvoiceStatus
from app.schemas.sales.sales import Invoice


def void_invoice_for_shipment_reopen(db: Session, invoice: Invoice) -> None:
    """Stage the existing shipment-reopen invoice values in the supplied Session.

    The caller has already locked the invoice and completed the all-invoice
    eligibility checks. This writer performs no policy checks, flush, audit or
    commit; the shipment-reopen operation owns the outer transaction.
    """
    db.add(invoice)
    invoice.status = InvoiceStatus.VOID
    invoice.amount = Decimal("0.00")
