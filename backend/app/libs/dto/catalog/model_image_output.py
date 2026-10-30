from datetime import datetime
from typing import Optional

from app.libs.dto.common import ORMModel


class ModelImageOut(ORMModel):
    id: int
    file_url: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    image_type: Optional[str] = None
    is_primary: bool
    created_at: datetime


class ModelImageUploadOut(ORMModel):
    """Stable response contract for one completed multipart image upload."""

    id: int
    file_url: str
