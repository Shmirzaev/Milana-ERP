"""Shipment invoice writes in the caller's existing transaction."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.libs.enums.finance import InvoiceStatus
from app.schemas.sales.sales import Invoice


def stage_shipment_invoice(
    db: Session, *, sales_order_id: int, invoice_no: str, amount: float,
    status: InvoiceStatus, issued_at: datetime, due_date: datetime,
) -> Invoice:
    """Stage the decided invoice; the shipment caller controls flushing."""
    invoice = Invoice(sales_order_id=sales_order_id, invoice_no=invoice_no,
                      amount=amount, status=status, issued_at=issued_at, due_date=due_date)
    db.add(invoice)
    return invoice


def set_shipment_invoice_amount(db: Session, invoice: Invoice, amount: Decimal) -> None:
    """Apply the amount decided by the shipment coordinator."""
    invoice.amount = amount
