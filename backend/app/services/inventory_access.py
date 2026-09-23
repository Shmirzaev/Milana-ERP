"""User-specific material-only inventory scope; shared Storage roles stay intact."""
from fastapi import HTTPException
from sqlalchemy.orm import Session, lazyload, load_only

from app.core.deps import user_permissions
from app.models import Item, MaterialReservation, StockBatch, User

MATERIALS_ONLY = "inventory.materials_only"
MATERIAL_CATEGORIES = ("fabric", "semi_finished")


def materials_only(user: User) -> bool:
    return MATERIALS_ONLY in user_permissions(user)


def require_accessories(user: User) -> None:
    if materials_only(user):
        raise HTTPException(403, "Accessory access is disabled for this user")


def scoped_group(user: User, group: str | None, category: str | None = None) -> str | None:
    if not materials_only(user):
        return group
    if (group and group != "materials") or (category and category not in MATERIAL_CATEGORIES):
        raise HTTPException(403, "Only material inventory is available to this user")
    return "materials"


def require_category(user: User, category: str) -> None:
    if materials_only(user) and category not in MATERIAL_CATEGORIES:
        raise HTTPException(403, "Only material inventory is available to this user")


def require_item(db: Session, user: User, item_id: int | None) -> None:
    if materials_only(user) and item_id:
        item = db.get(Item, item_id, options=(load_only(Item.id, Item.category),))
        if item is not None:
            require_category(user, item.category)


def require_batch(db: Session, user: User, batch_id: int | None) -> None:
    if materials_only(user) and batch_id:
        row = (
            db.query(StockBatch.item_id, Item.category)
            .join(Item, Item.id == StockBatch.item_id)
            .filter(StockBatch.id == batch_id)
            .first()
        )
        if row is not None:
            require_category(user, row.category)


def require_reservation(db: Session, user: User, reservation_id: int) -> None:
    if materials_only(user):
        reservation = db.query(MaterialReservation).options(
            load_only(
                MaterialReservation.id,
                MaterialReservation.item_id,
                MaterialReservation.stock_batch_id,
            ),
            lazyload(MaterialReservation.item),
            lazyload(MaterialReservation.stock_batch),
            lazyload(MaterialReservation.warehouse),
        ).filter(MaterialReservation.id == reservation_id).first()
        if reservation:
            require_item(db, user, reservation.item_id)
            require_batch(db, user, reservation.stock_batch_id)
