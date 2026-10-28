"""Collection creation persistence in the caller's transaction."""

from sqlalchemy.orm import Session

from app.libs.enums.catalog import CollectionStatus
from app.schemas.catalog.catalog import Collection


def insert_collection(
    db: Session,
    *,
    brand_id: int,
    name: str,
    season: str | None,
    year: int,
    description: str | None,
    status: CollectionStatus,
) -> Collection:
    row = Collection(
        brand_id=brand_id,
        name=name,
        season=season,
        year=year,
        description=description,
        status=status.value,
    )
    db.add(row)
    db.flush()
    return row
