"""Existing notification operation contract, independently asserted on both databases."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.api.routes import notifications as routes
from app.schemas import AuditLog, Notification, User
from app.tests.test_notification_fanout_batching import notification_sessions as notification_sessions


@pytest.fixture
def notification_case(notification_sessions):
    with notification_sessions() as db:
        actor = User(name="Manager", email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                     extra_permissions=["management.view"], is_active=True)
        other = User(name="Recipient", email=f"{uuid4().hex}@example.invalid", password_hash="unused", is_active=True)
        db.add_all([actor, other]); db.flush()
        own = Notification(user_id=actor.id, title="Own unread", is_read=False)
        foreign = Notification(user_id=other.id, title="Other unread", is_read=False)
        db.add_all([own, foreign]); db.commit()
        yield db, actor, other, own, foreign


def test_send_normalization_notification_and_audit(notification_case):
    db, actor, other, own, foreign = notification_case
    result = routes.send_notification(routes.NotificationSendIn(target_type="user_id", user_id=other.id,
              title=" Notice ", message=" detail ", link=" /tasks "), db, actor)
    assert result["message"] == "notification_sent" and result["created_count"] == 1
    assert result["recipients"] == [{"user_id": other.id, "name": other.name}]
    row = db.get(Notification, result["notification_ids"][0])
    assert (row.title, row.message, row.link, row.is_read) == ("Notice", "detail", "/tasks", False)
    audit = db.query(AuditLog).filter_by(action="mcp_send_notification").one()
    assert audit.new_value_json["recipient_user_ids"] == [other.id]
    assert audit.new_value_json["source"] == "mcp"


def test_send_refusal_and_commit_failure_leave_no_partial_effects(notification_case):
    db, actor, other, own, foreign = notification_case
    with pytest.raises(HTTPException) as exc:
        routes.send_notification(routes.NotificationSendIn(target_type="user_id", user_id=other.id,
                                 title="Bad link", link="https://example.com"), db, actor)
    assert exc.value.status_code == 400
    before = db.query(Notification).count()
    def fail(_):
        raise RuntimeError("commit failure")
    event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError, match="commit failure"):
        routes.send_notification(routes.NotificationSendIn(target_type="user_id", user_id=other.id,
                                 title="Failed send"), db, actor)
    event.remove(db, "before_commit", fail); db.rollback()
    assert db.query(Notification).count() == before
    assert db.query(AuditLog).filter_by(action="mcp_send_notification").count() == 0
