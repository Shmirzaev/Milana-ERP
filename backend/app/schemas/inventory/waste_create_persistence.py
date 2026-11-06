"""Persistence for manually recorded waste."""

from sqlalchemy.orm import Session

from app.libs.enums.inventory import WasteStatus
from app.schemas.inventory.waste import WasteRecord


def insert_manual_waste(db: Session, *, data: dict, created_by: int) -> WasteRecord:
    record = WasteRecord(**data, created_by=created_by, status=WasteStatus.RECORDED.value)
    db.add(record)
    db.flush()
    return record
