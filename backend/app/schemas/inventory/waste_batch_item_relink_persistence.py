"""Waste persistence for a stock batch material correction."""
from sqlalchemy.orm import Session
from app.schemas.inventory.waste import WasteRecord


def relink_batch_item(db: Session, batch_id: int, item_id: int) -> int:
    return db.query(WasteRecord).filter(WasteRecord.batch_id == batch_id).update(
        {WasteRecord.item_id: item_id}, synchronize_session=False,
    )
