"""Existing notification operation contract, independently asserted on both databases."""
from uuid import uuid4
import pytest
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
        db.add_all([own, foreign])
        db.add_all([Notification(user_id=user.id, title=f"Bulk {i}", is_read=False)
                    for user in (actor, other) for i in range(25)])
        db.add(Notification(user_id=actor.id, title="Already read", is_read=True))
        db.commit()
        yield db, actor, other, own, foreign


def test_read_all_own_rows_only_and_repeat(notification_case):
    db, actor, other, own, foreign = notification_case
    result = routes.mark_all_read(db, actor)
    assert result == {"message": "all read"}
    routes.mark_all_read(db, actor)
    db.expire_all()
    assert db.get(Notification, own.id).is_read is True
    assert db.get(Notification, foreign.id).is_read is False
    assert db.query(Notification).filter_by(user_id=actor.id, is_read=False).count() == 0
    assert db.query(Notification).filter_by(user_id=other.id, is_read=False).count() == 26
    assert db.query(AuditLog).count() == 0


def test_read_all_failure_preserves_unread_state(notification_case):
    db, actor, other, own, foreign = notification_case
    def fail(_):
        raise RuntimeError("commit failure")
    event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError, match="commit failure"):
        routes.mark_all_read(db, actor)
    event.remove(db, "before_commit", fail); db.rollback()
    assert db.get(Notification, own.id).is_read is False
    assert db.get(Notification, foreign.id).is_read is False
