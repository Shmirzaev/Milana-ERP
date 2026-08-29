from datetime import datetime, timezone
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

from app.core.deps import DbSession, CurrentUser, require_permissions
from app.models import Department, Notification, Role, User
from app.schemas.tasks import NotificationOut
from app.services.audit import log_action
from app.services.notifications import notify

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationSendIn(BaseModel):
    target_type: Literal["user_id", "department", "safe_group"]
    user_id: int | None = Field(default=None, ge=1)
    department: str | None = Field(default=None, min_length=1, max_length=64)
    safe_group: Literal["management", "admins"] | None = None
    title: str = Field(min_length=1, max_length=255)
    message: str | None = Field(default=None, max_length=2000)
    link: str | None = Field(default=None, max_length=512)
    entity_type: str | None = Field(default=None, max_length=64)
    entity_id: int | None = Field(default=None, ge=1)


def _max_bulk_recipients() -> int:
    try:
        value = int(os.getenv("ERP_MCP_MAX_BULK_RECIPIENTS", "25"))
    except ValueError:
        value = 25
    return max(1, min(value, 250))


def _safe_link(link: str | None) -> str | None:
    value = (link or "").strip()
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        raise HTTPException(400, "Notification link must be a relative ERP path")
    return value


def _resolve_recipients(payload: NotificationSendIn, db: DbSession) -> list[User]:
    if payload.target_type == "user_id":
        if payload.user_id is None:
            raise HTTPException(400, "user_id is required for target_type=user_id")
        user = db.get(User, payload.user_id)
        if not user or not user.is_active:
            raise HTTPException(404, "Recipient user not found")
        return [user]

    if payload.target_type == "department":
        value = (payload.department or "").strip().lower()
        if not value:
            raise HTTPException(400, "department is required for target_type=department")
        department = (
            db.query(Department)
            .filter((func.lower(Department.code) == value) | (func.lower(Department.name) == value))
            .first()
        )
        if not department:
            raise HTTPException(404, "Recipient department not found")
        return (
            db.query(User)
            .filter(User.department_id == department.id, User.is_active.is_(True))
            .order_by(User.id.asc())
            .all()
        )

    if payload.target_type == "safe_group":
        group = payload.safe_group
        if group == "management":
            role_names = ["Management"]
        elif group == "admins":
            role_names = ["Admin", "Super Admin"]
        else:
            raise HTTPException(400, "safe_group must be management or admins")
        return (
            db.query(User)
            .join(Role, Role.id == User.role_id)
            .filter(Role.name.in_(role_names), User.is_active.is_(True))
            .order_by(User.id.asc())
            .all()
        )

    raise HTTPException(400, "Unsupported recipient target")


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
def send_notification(
    payload: NotificationSendIn,
    db: DbSession,
    current: User = Depends(require_permissions("management.view", "*")),
):
    recipients = _resolve_recipients(payload, db)
    if not recipients:
        raise HTTPException(404, "No active recipients found")
    max_recipients = _max_bulk_recipients()
    if len(recipients) > max_recipients:
        raise HTTPException(
            400,
            f"Recipient count {len(recipients)} exceeds ERP_MCP_MAX_BULK_RECIPIENTS={max_recipients}",
        )

    title = payload.title.strip()
    message = payload.message.strip() if payload.message else None
    link = _safe_link(payload.link)
    created_ids: list[int] = []
    for recipient in recipients:
        created = notify(db, user_id=recipient.id, title=title, message=message, link=link)
        created_ids.append(int(created.id))

    linked_entity = None
    if payload.entity_type or payload.entity_id:
        linked_entity = {"entity_type": payload.entity_type, "entity_id": payload.entity_id}

    log_action(
        db,
        current,
        "mcp_send_notification",
        "Notification",
        None,
        new_value={
            "requested_by": current.id,
            "recipient_user_ids": [int(user.id) for user in recipients],
            "title": title,
            "message": message,
            "link": link,
            "linked_entity": linked_entity,
            "created_count": len(created_ids),
            "source": "mcp",
        },
    )
    db.commit()
    return {
        "message": "notification_sent",
        "created_count": len(created_ids),
        "notification_ids": created_ids,
        "recipients": [{"user_id": int(user.id), "name": user.name} for user in recipients],
        "title": title,
        "link": link,
        "linked_entity": linked_entity,
        "requested_by": {"user_id": int(current.id), "name": current.name},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


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
