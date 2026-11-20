"""Catalog persistence for a stock batch material correction."""
from sqlalchemy.orm import Session
from app.schemas.catalog.catalog import ModelBOM


def relink_batch_item(db: Session, batch_id: int, item_id: int) -> int:
    return db.query(ModelBOM).filter(ModelBOM.stock_batch_id == batch_id).update(
        {ModelBOM.item_id: item_id}, synchronize_session=False,
    )
