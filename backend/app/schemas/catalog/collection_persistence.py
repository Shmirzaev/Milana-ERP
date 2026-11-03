"""Collection creation persistence in the caller's transaction."""

from sqlalchemy.orm import Session

from app.libs.enums.catalog import CollectionStatus
from app.libs.types.catalog import CollectionUpdateCommand
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


def apply_collection_update(
    db: Session, collection: Collection, fields: CollectionUpdateCommand
) -> None:
    """Apply the service-selected fields without taking transaction ownership."""
    if "brand_id" in fields:
        collection.brand_id = fields["brand_id"]
    if "name" in fields:
        collection.name = fields["name"]
    if "season" in fields:
        collection.season = fields["season"]
    if "year" in fields:
        collection.year = fields["year"]
    if "description" in fields:
        collection.description = fields["description"]
    if "status" in fields:
        collection.status = fields["status"].value
    if "unchanged_legacy_status" in fields:
        collection.status = fields["unchanged_legacy_status"]
