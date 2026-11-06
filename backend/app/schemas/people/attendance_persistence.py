"""Attendance writes in the business operation's supplied Session."""
from sqlalchemy.orm import Session

from app.schemas import AttendanceDevice


def insert_managed_device(db: Session, *, values: dict) -> AttendanceDevice:
    device = AttendanceDevice(**values)
    db.add(device)
    return device


def update_managed_device(db: Session, *, device: AttendanceDevice, changes: dict) -> None:
    for field, value in changes.items():
        setattr(device, field, value)
