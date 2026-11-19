"""Persistence for catalog model images; the caller owns the transaction."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import ModelImage


def delete_model_image(db: Session, image: ModelImage) -> None:
    """Mark an already validated image for deletion without flushing or committing."""
    db.delete(image)


def insert_url_image(
    db: Session, *, model_id: int, file_url: str, file_name: str | None,
    content_type: str | None, image_type: str | None, is_primary: bool,
) -> ModelImage:
    """Apply the service's decision and flush for its audit; never commit."""
    if is_primary:
        db.query(ModelImage).filter(
            ModelImage.model_id == model_id, ModelImage.is_primary.is_(True)
        ).update({"is_primary": False}, synchronize_session=False)
    image = ModelImage(
        model_id=model_id, file_url=file_url, file_name=file_name,
        content_type=content_type, image_type=image_type, is_primary=is_primary,
    )
    db.add(image)
    db.flush()
    return image
