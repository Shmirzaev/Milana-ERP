from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator

from app.libs.enums.catalog import ModelImageUploadType


def _normalize_model_image_upload_type(value: object) -> object:
    """Normalize accepted upload spelling before validating its enum value."""
    if value is None or isinstance(value, ModelImageUploadType):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized or None
    return value


ModelImageUploadInput = Annotated[
    ModelImageUploadType | None,
    BeforeValidator(_normalize_model_image_upload_type),
]

# Multipart upload is enum-typed. This does not narrow the separate
# ModelImageIn URL-attachment contract or historical mapped values.


class ModelImageIn(BaseModel):
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    image_type: Optional[str] = None
    is_primary: bool = False
