"""Schema-owned persistence operations for Catalog partner records."""

from sqlalchemy.orm import Session

from app.schemas.catalog.partners import Customer


def insert_customer(
    db: Session,
    *,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> Customer:
    """Add and flush one customer in the caller's transaction.

    The caller owns validation, audit, commit and refresh. This persistence
    operation performs no queries and never commits or rolls back.
    """
    customer = Customer(
        name=name,
        phone=phone,
        email=email,
        address=address,
        notes=notes,
    )
    db.add(customer)
    db.flush()
    return customer
