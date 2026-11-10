"""Catalog persistence for a price sourced from a completed request."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import Model


def apply_request_selling_price(
    db: Session, model: Model, *, price: Decimal, request_id: int, updated_at: datetime
) -> None:
    """Apply the decided price and flush in the caller's transaction."""
    model.selling_price = price
    model.selling_price_currency = "USD"
    model.selling_price_source = "price_request"
    model.selling_price_request_id = request_id
    model.selling_price_updated_at = updated_at
    db.flush()


def apply_catalog_selling_price(db: Session, model: Model, *, price: Decimal, updated_at: datetime) -> None:
    """Apply an authorized imported price, preserving all other model fields."""
    model.selling_price = price
    model.selling_price_currency = "USD"
    model.selling_price_source = "catalog"
    model.selling_price_request_id = None
    model.selling_price_updated_at = updated_at
    db.flush()
