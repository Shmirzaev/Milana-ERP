
from fastapi import APIRouter, Depends

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.schemas import User
from app.libs.dto.work_management.tasks import NotificationOut
from app.models.audit_service import log_action
from app.models.notifications_service import notify_many
from app.libs.dto.work_management.notification_send import NotificationSendIn
from app.models.work_management.notifications_service import (
    list_my_notifications as list_my_notifications_operation,
    mark_all_read as mark_all_read_operation,
    mark_read as mark_read_operation,
    notification_summary as notification_summary_operation,
    send_notification as send_notification_operation,
    unread_count as unread_count_operation,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_my_notifications(db: DbSession, current: CurrentUser, only_unread: bool = False, limit: int = 50):
    return list_my_notifications_operation(db, current, only_unread, limit)


@router.get("/unread-count")
def unread_count(db: DbSession, current: CurrentUser):
    return unread_count_operation(db, current)


@router.get("/summary")
def notification_summary(db: DbSession, current: CurrentUser, limit: int = 10):
    return notification_summary_operation(db, current, limit)


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
