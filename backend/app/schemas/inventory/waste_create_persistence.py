"""Persistence for manually recorded waste."""

from sqlalchemy.orm import Session

from app.schemas.inventory.waste import WasteRecord


def insert_manual_waste(db: Session, *, data: dict, created_by: int) -> WasteRecord:
    record = WasteRecord(**data, created_by=created_by, status="recorded")
    db.add(record)
    db.flush()
    return record
