"""Mapped writes for a service-approved roll-weight replacement."""

from sqlalchemy.orm import Session

from app.schemas.inventory.inventory import StockBatch


def replace_roll_weights(
    db: Session, batch: StockBatch, *, roll_weights: list[float], piece_count: int | None
) -> None:
    """Apply the values in the caller's transaction."""
    batch.roll_weights_kg = roll_weights
    batch.piece_count = piece_count
