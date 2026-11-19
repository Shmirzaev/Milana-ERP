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


def test_read_own_rows_only_and_repeat(notification_case):
    db, actor, other, own, foreign = notification_case
    result = routes.mark_read(own.id, db, actor)
    assert result.id == own.id and result.is_read is True
    routes.mark_read(own.id, db, actor)
    db.expire_all()
    assert db.get(Notification, own.id).is_read is True
    assert db.get(Notification, foreign.id).is_read is False
    assert db.query(AuditLog).count() == 0


def test_read_failure_preserves_unread_state(notification_case):
    db, actor, other, own, foreign = notification_case
    with pytest.raises(HTTPException) as exc:
        routes.mark_read(foreign.id, db, actor)
    assert exc.value.status_code == 404
    def fail(_):
        raise RuntimeError("commit failure")
    event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError, match="commit failure"):
        routes.mark_read(own.id, db, actor)
    event.remove(db, "before_commit", fail); db.rollback()
    assert db.get(Notification, own.id).is_read is False
    assert db.get(Notification, foreign.id).is_read is False
