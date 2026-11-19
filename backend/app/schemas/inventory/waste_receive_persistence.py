"""Persistence for the waste receipt operation."""

from sqlalchemy.orm import Session

from app.schemas.inventory.waste import WasteRecord


def set_received(db: Session, record: WasteRecord) -> None:
    """Apply the service's approved transition in the caller's transaction."""
    record.status = "received_by_waste_department"
