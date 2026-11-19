"""Persist a validated family member's paid-operation document."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def set_model_paid_operations_details(db: Session, row: Model, details: dict) -> None:
    """Assign within the caller's transaction; the service controls audit and commit."""
    row.details_json = details
