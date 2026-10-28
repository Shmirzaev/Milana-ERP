"""Schema-owned persistence operations for Catalog partner records."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import CustomerUpdateCommand
from app.schemas.catalog.partners import Customer, Supplier


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


def insert_supplier(
    db: Session,
    *,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    notes: str | None = None,
) -> Supplier:
    """Add and flush one supplier in the caller's transaction."""
    supplier = Supplier(
        name=name,
        phone=phone,
        email=email,
        address=address,
        notes=notes,
    )
    db.add(supplier)
    db.flush()
    return supplier


def apply_customer_update(db: Session, customer: Customer, fields: CustomerUpdateCommand) -> None:
    """Apply supplied fields; the caller owns audit, flush and commit."""
    customer.name = fields["name"]
    if "phone" in fields:
        customer.phone = fields["phone"]
    if "email" in fields:
        customer.email = fields["email"]
    if "address" in fields:
        customer.address = fields["address"]
    if "notes" in fields:
        customer.notes = fields["notes"]
