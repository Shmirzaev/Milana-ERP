"""Schema-owned persistence for the Model image upload operation."""

from sqlalchemy.orm import Session

from app.libs.types.catalog import ModelImageUploadCommand
from app.schemas.catalog.catalog import ModelImage


def insert_uploaded_model_image(db: Session, command: ModelImageUploadCommand) -> int:
    """Apply the decided primary flag and insert one uploaded image row.

    The service retains model/scope and actor checks, file lifecycle, audit and
    the single outer commit. This operation uses the worker-owned Session,
    flushes only to obtain the image ID, and never commits.
    """

    if command.make_primary:
        db.query(ModelImage).filter(
            ModelImage.model_id == command.model_id,
            ModelImage.is_primary.is_(True),
        ).update({"is_primary": False}, synchronize_session=False)

    image = ModelImage(
        model_id=command.model_id,
        file_url=command.file_url,
        file_name=command.original_name,
        content_type=command.stored_content_type,
        # Upload bytes live in managed storage, not a duplicate BYTEA.
        file_data=None,
        image_type=command.image_type.value if command.image_type else None,
        is_primary=command.make_primary,
    )
    db.add(image)
    db.flush()
    return int(image.id)
