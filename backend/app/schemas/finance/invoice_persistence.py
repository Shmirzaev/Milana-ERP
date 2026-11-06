"""Schema-owned insert for the Finance invoice operations.

Manual Finance issuance, sales generation and customer receipt auto-issuance
write through this helper. The authoritative Invoice mapping
remains in schemas.sales.sales. Finance's service decides the amount, status,
number and time and owns the parent lock, audit and outer commit. This helper
uses that same Session and only flushes.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.finance import InvoiceStatus
from app.schemas.sales.sales import Invoice


def insert_order_invoice(
    db: Session,
    *,
    sales_order_id: int,
    invoice_no: str,
    amount: Decimal,
    status: InvoiceStatus,
    issued_at: datetime,
) -> Invoice:
    """Stage and flush the decided invoice, without committing its transaction."""
    invoice = Invoice(
        sales_order_id=sales_order_id,
        invoice_no=invoice_no,
        amount=amount,
        status=status,
        issued_at=issued_at,
    )
    db.add(invoice)
    db.flush()
    return invoice
