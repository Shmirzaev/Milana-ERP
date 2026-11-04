"""Persistence for catalog model images; the caller owns the transaction."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import ModelImage


def delete_model_image(db: Session, image: ModelImage) -> None:
    """Mark an already validated image for deletion without flushing or committing."""
    db.delete(image)
