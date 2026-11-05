"""Mapped writes for the catalog model update operation."""

from typing import Any

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def apply_model_update(db: Session, *, row: Model, values: dict[str, Any]) -> Model:
    """Apply service-decided fields without flushing or controlling the transaction."""
    for key, value in values.items():
        setattr(row, key, value)
    return row
