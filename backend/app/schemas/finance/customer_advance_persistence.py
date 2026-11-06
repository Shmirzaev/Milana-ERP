"""Persistence for a customer advance, within the caller's transaction."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.sales.sales import Payment


def insert_customer_advance(
    db: Session,
    *,
    customer_id: int,
    amount: Decimal,
    payment_method: str | None,
    paid_at: datetime,
    notes: str | None,
) -> Payment:
    """Stage and flush the already-decided advance without committing."""
    payment = Payment(
        invoice_id=None,
        customer_id=customer_id,
        amount=amount,
        payment_method=payment_method,
        paid_at=paid_at,
        notes=notes,
    )
    db.add(payment)
    db.flush()
    return payment
