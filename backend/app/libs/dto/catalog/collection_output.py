from typing import Optional

from app.libs.dto.common import ORMModel
from app.libs.enums.catalog import CollectionStatus


class CollectionOut(ORMModel):
    id: int
    brand_id: int
    name: str
    season: Optional[str] = None
    year: int
    description: Optional[str] = None
    status: str


class CollectionCreateOut(CollectionOut):
    """Typed result for a new row; list/get/PATCH may expose historical states."""

    status: CollectionStatus
