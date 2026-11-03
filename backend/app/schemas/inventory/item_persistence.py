"""Schema-owned Item writes using the caller's transaction."""

from sqlalchemy.orm import Session

from app.libs.types.inventory import ItemInsertCommand, ItemUpdateCommand
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


def update_item(db: Session, item: Item, command: ItemUpdateCommand) -> Item:
    """Assign normalized Item fields; the caller owns flush and transaction."""
    item.sku = command.sku
    item.name = command.name
    item.category = command.category
    item.unit = command.unit
    item.default_cost = command.default_cost
    item.reorder_level = command.reorder_level
    item.track_batch = command.track_batch
    item.is_active = command.is_active
    item.image_url = command.image_url
    item.composition_json = command.composition_json
    return item
