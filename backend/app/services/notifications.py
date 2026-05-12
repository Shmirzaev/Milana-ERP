from sqlalchemy.orm import Session

from app.models import Notification


def notify(db: Session, user_id: int, title: str, message: str | None = None, commit: bool = False) -> Notification:
    n = Notification(user_id=user_id, title=title, message=message)
    db.add(n)
    if commit:
        db.commit()
    else:
        db.flush()
    return n
