"""Narrow batch identity correction in the caller's transaction."""
from sqlalchemy.orm import Session

from app.schemas.inventory.inventory import StockBatch


def set_batch_number(db: Session, batch: StockBatch, batch_no: str) -> None:
    """Apply an already authorized number; never commit or change stock."""
    batch.batch_no = batch_no
