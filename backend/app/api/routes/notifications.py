from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser
from app.models import Notification
from app.schemas.tasks import NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_my_notifications(db: DbSession, current: CurrentUser, only_unread: bool = False, limit: int = 50):
    qry = db.query(Notification).filter(Notification.user_id == current.id)
    if only_unread:
        qry = qry.filter(Notification.is_read.is_(False))
    return qry.order_by(Notification.id.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(db: DbSession, current: CurrentUser):
    n = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current.id, Notification.is_read.is_(False),
    ).scalar() or 0
    return {"count": int(n)}


@router.post("/{nid}/read", response_model=NotificationOut)
def mark_read(nid: int, db: DbSession, current: CurrentUser):
    n = db.get(Notification, nid)
    if not n or n.user_id != current.id:
        raise HTTPException(404, "Notification not found")
    n.is_read = True
    db.commit(); db.refresh(n)
    return n


@router.post("/read-all")
def mark_all_read(db: DbSession, current: CurrentUser):
    db.query(Notification).filter(
        Notification.user_id == current.id, Notification.is_read.is_(False),
    ).update({Notification.is_read: True})
    db.commit()
    return {"message": "all read"}
