
from fastapi import APIRouter, Depends
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.core.pagination import clamp_pagination
from app.schemas import Notification, User
from app.libs.dto.work_management.tasks import NotificationOut
from app.models.audit_service import log_action
from app.models.notifications_service import notify_many
from app.libs.dto.work_management.notification_send import NotificationSendIn
from app.models.work_management.notifications_service import mark_all_read as mark_all_read_operation, mark_read as mark_read_operation, send_notification as send_notification_operation

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_my_notifications(db: DbSession, current: CurrentUser, only_unread: bool = False, limit: int = 50):
    safe_limit = 0 if limit == 0 else clamp_pagination(page_size=limit)[1]
    qry = db.query(Notification).filter(Notification.user_id == current.id)
    if only_unread:
        qry = qry.filter(Notification.is_read.is_(False))
    return qry.order_by(Notification.id.desc()).limit(safe_limit).all()


@router.get("/unread-count")
def unread_count(db: DbSession, current: CurrentUser):
    n = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current.id, Notification.is_read.is_(False),
    ).scalar() or 0
    return {"count": int(n)}


@router.get("/summary")
def notification_summary(db: DbSession, current: CurrentUser, limit: int = 10):
    safe_limit = max(1, min(int(limit or 10), 50))
    count = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current.id,
        Notification.is_read.is_(False),
    ).scalar() or 0
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == current.id, Notification.is_read.is_(False))
        .order_by(Notification.id.desc())
        .limit(safe_limit)
        .all()
    )
    return {
        "count": int(count),
        "rows": [NotificationOut.model_validate(row).model_dump(mode="json") for row in rows],
    }


@router.post("/send")
def send_notification(payload: NotificationSendIn, db: DbSession,
                      current: User = Depends(require_permissions("management.view", "*"))):
    return send_notification_operation(payload, db, current, audit=log_action, deliver=notify_many)


@router.post("/{nid}/read", response_model=NotificationOut)
def mark_read(nid: int, db: DbSession, current: CurrentUser):
    return mark_read_operation(nid, db, current)


@router.post("/read-all")
def mark_all_read(db: DbSession, current: CurrentUser):
    return mark_all_read_operation(db, current)
