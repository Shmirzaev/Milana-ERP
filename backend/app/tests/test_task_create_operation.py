"""Creation effects shared by the route today and the extracted operation."""
from uuid import uuid4

import pytest

from app.api.routes import tasks
from app.libs.dto.work_management.tasks import TaskIn
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_task_broadcast_batching import _actor, broadcast_sessions as broadcast_sessions


def test_single_creation_persists_task_notification_and_audit(broadcast_sessions):
    with broadcast_sessions() as db:
        actor = _actor(db)
        recipient = User(name="Recipient", email=f"{uuid4().hex}@example.invalid",
                         password_hash="unused", is_active=True)
        db.add(recipient)
        db.commit()
        title = f"Single {uuid4().hex}"

        created = tasks.create_task(TaskIn(title=title, description="x" * 300,
                                           assigned_to=recipient.id), db, actor)

        assert created.assigned_to == recipient.id
        assert db.query(Task).filter_by(title=title).count() == 1
        notice = db.query(Notification).filter_by(user_id=recipient.id, title=f"New task: {title}").one()
        assert notice.message == "x" * 280 and notice.link is None and notice.is_read is False
        audit = db.query(AuditLog).filter_by(entity_type="Task", entity_id=created.id).one()
        assert audit.new_value_json == {"title": title, "assigned_to": recipient.id}


def test_single_audit_failure_rolls_back_task_and_notification(broadcast_sessions, monkeypatch):
    with broadcast_sessions() as db:
        actor = _actor(db)
        recipient = User(name="Recipient", email=f"{uuid4().hex}@example.invalid",
                         password_hash="unused", is_active=True)
        db.add(recipient)
        db.commit()
        title = f"Rollback {uuid4().hex}"

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("Synthetic audit failure")

        monkeypatch.setattr(tasks, "log_action", fail_audit)
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            tasks.create_task(TaskIn(title=title, assigned_to=recipient.id), db, actor)
        db.rollback()

        assert db.query(Task).filter_by(title=title).count() == 0
        assert db.query(Notification).filter_by(title=f"New task: {title}").count() == 0
