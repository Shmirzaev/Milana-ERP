import os

from sqlalchemy.orm import Session

from app.schemas import Notification
from app.schemas.core_persistence import add_notification_row, add_notification_rows


def max_bulk_recipients() -> int:
    """Return the shared, bounded notification fan-out limit."""
    try:
        value = int(os.getenv("ERP_MCP_MAX_BULK_RECIPIENTS", "25"))
    except ValueError:
        value = 25
    return max(1, min(value, 250))


def notify(
    db: Session,
    user_id: int,
    title: str,
    message: str | None = None,
    link: str | None = None,
    commit: bool = False,
) -> Notification:
    """Create an in-app notification. `link` is an optional frontend route
    the NotificationBell will navigate to when the user clicks the row."""
    n = add_notification_row(db, user_id=user_id, title=title, message=message, link=link)
    if commit:
        db.commit()
    else:
        db.flush()
    return n


def notify_many(
    db: Session,
    user_ids: list[int],
    title: str,
    message: str | None = None,
    link: str | None = None,
) -> list[Notification]:
    """Create an ordered notification fan-out with one flush boundary."""
    rows = add_notification_rows(
        db, user_ids=user_ids, title=title, message=message, link=link
    )
    db.flush()
    return rows
