from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from app.models import Invoice, Payment, SalesOrder


MANUAL_PAYMENT_METHODS = ("bank_transfer", "cash", "card")


def normalize_manual_payment_method(payment_method: str | None) -> str | None:
    if payment_method is None:
        return None
    normalized = payment_method.strip().lower()
    if normalized not in MANUAL_PAYMENT_METHODS:
        raise HTTPException(400, "Invalid payment_method; expected bank_transfer, cash, or card")
    return normalized


def invoice_paid_total(db: Session, invoice_id: int) -> Decimal:
    total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == invoice_id).scalar() or 0
    return Decimal(str(total))


def refresh_invoice_status(db: Session, invoice: Invoice) -> None:
    total_paid = invoice_paid_total(db, int(invoice.id))
    amount = Decimal(str(invoice.amount or 0))
    if amount <= 0 or total_paid >= amount:
        invoice.status = "paid"
    elif total_paid > 0:
        invoice.status = "partially_paid"
    else:
        invoice.status = "unpaid"


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
    # Serialize invoice payments before inserting or reading their total. Refresh
    # the caller's cached invoice after waiting; the lock lasts until commit.
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice.id)
        .options(load_only(
            Invoice.id,
            Invoice.sales_order_id,
            Invoice.invoice_no,
            Invoice.amount,
            Invoice.status,
        ))
        .populate_existing()
        .with_for_update(of=Invoice)
        .one()
    )
    if invoice.status in {"void", "cancelled"}:
        raise HTTPException(409, "Cannot pay a void or cancelled invoice")
    payment_method = normalize_manual_payment_method(payment_method)
    if customer_id is None and invoice.sales_order_id:
        customer_id = db.query(SalesOrder.customer_id).filter(SalesOrder.id == invoice.sales_order_id).scalar()
    payment = Payment(
        invoice_id=invoice.id,
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        paid_at=paid_at or datetime.now(timezone.utc),
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
    payment_method = normalize_manual_payment_method(payment_method)
    payment = Payment(
        invoice_id=None,
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        paid_at=paid_at or datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(payment)
    db.flush()
    return payment
