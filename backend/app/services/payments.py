from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Invoice, Payment


def invoice_paid_total(db: Session, invoice_id: int) -> float:
    total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(Payment.invoice_id == invoice_id).scalar() or 0
    return float(total)


def refresh_invoice_status(db: Session, invoice: Invoice) -> None:
    total_paid = invoice_paid_total(db, int(invoice.id))
    amount = float(invoice.amount or 0)
    if amount <= 0 or total_paid >= amount - 0.01:
        invoice.status = "paid"
    elif total_paid > 0.01:
        invoice.status = "partially_paid"
    else:
        invoice.status = "unpaid"


def create_invoice_payment(
    db: Session,
    invoice: Invoice,
    *,
    amount: float,
    payment_method: str | None = None,
    paid_at: datetime | None = None,
    notes: str | None = None,
) -> Payment:
    payment = Payment(
        invoice_id=invoice.id,
        amount=amount,
        payment_method=payment_method,
        paid_at=paid_at or datetime.now(timezone.utc),
        notes=notes,
    )
    db.add(payment)
    db.flush()
    refresh_invoice_status(db, invoice)
    return payment
