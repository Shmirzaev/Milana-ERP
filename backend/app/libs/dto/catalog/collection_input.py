from typing import Optional

from pydantic import BaseModel
from app.libs.enums.catalog import CollectionStatus


class CollectionIn(BaseModel):
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str = "draft"


class CollectionCreateIn(CollectionIn):
    """New collections use canonical states; PATCH keeps legacy compatibility."""

    status: CollectionStatus = CollectionStatus.DRAFT
