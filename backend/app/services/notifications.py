from sqlalchemy.orm import Session

from app.models import Notification


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
    n = Notification(user_id=user_id, title=title, message=message, link=link)
    db.add(n)
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
    rows = [
        Notification(user_id=user_id, title=title, message=message, link=link)
        for user_id in user_ids
    ]
    db.add_all(rows)
    db.flush()
    return rows
