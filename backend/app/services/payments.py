from datetime import datetime, timezone
from decimal import Decimal
from fastapi import HTTPException

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dt import as_utc
from app.models import Invoice, Payment, SalesOrder


USD_SETTLEMENT_TOLERANCE = Decimal("1.00")
REVERSED_INVOICE_STATUSES = frozenset({"void", "cancelled"})


def money_decimal(value: Decimal | float | int | None) -> Decimal:
    """Keep money exact until the API serialization boundary."""
    return Decimal(str(value or 0))


def invoice_payment_status(
    amount: Decimal | float | int,
    total_paid: Decimal | float | int,
    current_status: str | None = None,
) -> str:
    """Apply the approved USD settlement tolerance without altering the ledger.

    Invoices and payments currently have no currency field: their commercial
    ledger is USD. This tolerance must not be used for other currencies.
    """
    if current_status in REVERSED_INVOICE_STATUSES:
        return current_status
    amount = money_decimal(amount)
    total_paid = money_decimal(total_paid)
    if amount - total_paid <= USD_SETTLEMENT_TOLERANCE:
        return "paid"
    return "partially_paid" if total_paid > 0 else "unpaid"


def invoice_paid_total(db: Session, invoice_id: int) -> Decimal:
    total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == invoice_id).scalar() or 0
    return money_decimal(total)


def refresh_invoice_status(db: Session, invoice: Invoice) -> None:
    total_paid = invoice_paid_total(db, int(invoice.id))
    invoice.status = invoice_payment_status(invoice.amount, total_paid, invoice.status)


def create_invoice_payment(
    db: Session,
    invoice: Invoice,
    *,
    amount: Decimal | float,
    customer_id: int | None = None,
    payment_method: str | None = None,
    paid_at: datetime | None = None,
    notes: str | None = None,
) -> Payment:
    invoice = db.query(Invoice).filter_by(id=invoice.id).populate_existing().with_for_update().one()
    if invoice.status in REVERSED_INVOICE_STATUSES:
        raise HTTPException(409, "Cannot pay a reversed or cancelled invoice")
    if customer_id is None and invoice.sales_order_id:
        customer_id = db.query(SalesOrder.customer_id).filter(SalesOrder.id == invoice.sales_order_id).scalar()
    payment = Payment(
        invoice_id=invoice.id,
        customer_id=customer_id,
        amount=money_decimal(amount),
        payment_method=payment_method,
        paid_at=as_utc(paid_at) or datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(payment)
    db.flush()
    refresh_invoice_status(db, invoice)
    return payment


def create_customer_advance_payment(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal | float,
    payment_method: str | None = None,
    paid_at: datetime | None = None,
    notes: str | None = None,
) -> Payment:
    payment = Payment(
        invoice_id=None,
        customer_id=customer_id,
        amount=money_decimal(amount),
        payment_method=payment_method,
        paid_at=as_utc(paid_at) or datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(payment)
    db.flush()
    return payment
