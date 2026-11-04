"""Persistence for the catalog image upload operation."""

from sqlalchemy.orm import Session

from app.schemas.catalog.catalog import ModelImage


def add_uploaded_model_image(
    db: Session,
    *,
    model_id: int,
    file_url: str,
    file_name: str,
    content_type: str,
    image_type: str | None,
    is_primary: bool,
) -> ModelImage:
    if is_primary:
        db.query(ModelImage).filter(
            ModelImage.model_id == model_id,
            ModelImage.is_primary.is_(True),
        ).update({"is_primary": False}, synchronize_session=False)
    image = ModelImage(
        model_id=model_id,
        file_url=file_url,
        file_name=file_name,
        content_type=content_type,
        file_data=None,
        image_type=image_type,
        is_primary=is_primary,
    )
    db.add(image)
    db.flush()
    return image
