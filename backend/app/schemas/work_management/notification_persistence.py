"""Notification read-state writes in the supplied transaction."""
from sqlalchemy.orm import Session
from app.schemas.core import Notification


def mark_notification_read(db: Session, notification: Notification) -> None:
    notification.is_read = True


def mark_user_notifications_read(db: Session, *, user_id: int) -> None:
    db.query(Notification).filter(
        Notification.user_id == user_id, Notification.is_read.is_(False),
    ).update({Notification.is_read: True})
