"""Schema-owned Item insert using the caller's transaction."""

from sqlalchemy.orm import Session

from app.libs.types.inventory import ItemInsertCommand
from app.schemas.inventory.inventory import Item


def insert_item(db: Session, command: ItemInsertCommand) -> Item:
    """Add and flush one normalized Item; the caller owns audit and commit."""
    item = Item(
        sku=command.sku,
        name=command.name,
        category=command.category,
        unit=command.unit,
        default_cost=command.default_cost,
        reorder_level=command.reorder_level,
        track_batch=command.track_batch,
        is_active=command.is_active,
        image_url=command.image_url,
        composition_json=command.composition_json,
    )
    db.add(item)
    db.flush()
    return item


def set_item_image(db: Session, item: Item, image_url: str | None) -> None:
    """Assign the normalized image using the caller's transaction."""
    item.image_url = image_url
