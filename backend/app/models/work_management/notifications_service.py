"""Work-management notification operations and transaction boundaries."""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.deps import require_permissions
from app.schemas import Department, Notification, Role, User
from app.schemas.work_management.notification_persistence import mark_notification_read, mark_user_notifications_read
from app.libs.dto.work_management.notification_send import NotificationSendIn
from app.models.audit_service import log_action
from app.models.notifications_service import notify_many, _max_bulk_recipients


def _safe_link(link: str | None) -> str | None:
    value = (link or "").strip()
    if not value:
        return None
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        raise HTTPException(400, "Notification link must be a relative ERP path")
    return value


def _resolve_recipients(
    payload: NotificationSendIn,
    db: Session,
    *,
    max_recipients: int | None = None,
) -> list[User]:
    if payload.target_type == "user_id":
        if payload.user_id is None:
            raise HTTPException(400, "user_id is required for target_type=user_id")
        if payload.user_id > 2_147_483_647:
            raise HTTPException(404, "Recipient user not found")
        user = _recipient_user_query(db).filter(User.id == payload.user_id).first()
        if not user or not user.is_active:
            raise HTTPException(404, "Recipient user not found")
        return [user]

    if payload.target_type == "department":
        value = (payload.department or "").strip().lower()
        if not value:
            raise HTTPException(400, "department is required for target_type=department")
        department_id = (
            db.query(Department.id)
            .filter((func.lower(Department.code) == value) | (func.lower(Department.name) == value))
            .limit(1)
            .scalar()
        )
        if department_id is None:
            raise HTTPException(404, "Recipient department not found")
        query = (
            _recipient_user_query(db)
            .filter(User.department_id == department_id, User.is_active.is_(True))
            .order_by(User.id.asc())
        )
        if max_recipients is not None:
            query = query.limit(max_recipients + 1)
        return query.all()

    if payload.target_type == "safe_group":
        group = payload.safe_group
        if group == "management":
            role_names = ["Management"]
        elif group == "admins":
            role_names = ["Admin", "Super Admin"]
        else:
            raise HTTPException(400, "safe_group must be management or admins")
        query = (
            _recipient_user_query(db)
            .join(Role, Role.id == User.role_id)
            .filter(Role.name.in_(role_names), User.is_active.is_(True))
            .order_by(User.id.asc())
        )
        if max_recipients is not None:
            query = query.limit(max_recipients + 1)
        return query.all()

    raise HTTPException(400, "Unsupported recipient target")



def _recipient_user_query(db: Session):
    # Fan-out only needs recipient identity and the public response name.
    return db.query(User.id, User.name, User.is_active)


def send_notification(
    payload: NotificationSendIn,
    db: Session,
    current: User,
    *, audit=log_action, deliver=notify_many,
):
    require_permissions("management.view", "*")(current)
    max_recipients = _max_bulk_recipients()
    recipients = _resolve_recipients(payload, db, max_recipients=max_recipients)
    if not recipients:
        raise HTTPException(404, "No active recipients found")
    if len(recipients) > max_recipients:
        raise HTTPException(
            400,
            f"Recipient count exceeds ERP_MCP_MAX_BULK_RECIPIENTS={max_recipients}",
        )

    title = payload.title.strip()
    message = payload.message.strip() if payload.message else None
    link = _safe_link(payload.link)
    created = deliver(
        db,
        [int(recipient.id) for recipient in recipients],
        title=title,
        message=message,
        link=link,
    )
    created_ids = [int(row.id) for row in created]

    linked_entity = None
    if payload.entity_type or payload.entity_id:
        linked_entity = {"entity_type": payload.entity_type, "entity_id": payload.entity_id}

    audit(
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


def mark_read(nid: int, db: Session, current: User):
    n = db.get(Notification, nid)
    if not n or n.user_id != current.id:
        raise HTTPException(404, "Notification not found")
    mark_notification_read(db, n)
    db.commit(); db.refresh(n)
    return n


def mark_all_read(db: Session, current: User):
    mark_user_notifications_read(db, user_id=current.id)
    db.commit()
    return {"message": "all read"}
