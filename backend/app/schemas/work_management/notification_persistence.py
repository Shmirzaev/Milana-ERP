"""Notification read-state writes in the supplied transaction."""
from sqlalchemy.orm import Session
from app.schemas.core import Notification


def mark_notification_read(db: Session, notification: Notification) -> None:
    notification.is_read = True
