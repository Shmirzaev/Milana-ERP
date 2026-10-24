"""User-specific material-only inventory scope; shared Storage roles stay intact."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

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
        item = db.get(Item, item_id)
        if item:
            require_category(user, item.category)


def require_batch(db: Session, user: User, batch_id: int | None) -> None:
    if materials_only(user) and batch_id:
        batch = db.get(StockBatch, batch_id)
        if batch:
            require_item(db, user, batch.item_id)


def require_reservation(db: Session, user: User, reservation_id: int) -> None:
    if materials_only(user):
        reservation = db.get(MaterialReservation, reservation_id)
        if reservation:
            require_item(db, user, reservation.item_id)
            require_batch(db, user, reservation.stock_batch_id)
