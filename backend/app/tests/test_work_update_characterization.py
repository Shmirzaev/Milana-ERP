"""Characterization of the existing Work operation on SQLite and PostgreSQL."""
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.api.routes import tasks
from app.libs.dto.work_management.tasks import TaskUpdate
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_task_broadcast_batching import broadcast_sessions as broadcast_sessions


@pytest.fixture
def work_case(broadcast_sessions):
    with broadcast_sessions() as db:
        users = [User(name=name, email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                      extra_permissions=["tasks.manage"] if name == "Manager" else [], is_active=True)
                 for name in ("Manager", "Recipient", "Outsider")]
        db.add_all(users)
        db.flush()
        task = Task(title=f"Work {uuid4().hex}", description="x" * 300,
                    created_by=users[0].id, assigned_to=users[1].id, status="pending", priority="medium")
        db.add(task)
        db.commit()
        yield db, users[0], users[1], users[2], task


def test_update_reassignment_status_notification_and_audit(work_case):
    db, manager, recipient, outsider, task = work_case
    result = tasks.update_task(task.id, TaskUpdate(assigned_to=outsider.id, status="completed"), db, manager)
    assert result.assigned_to == outsider.id and result.completed_at is not None
    notice = db.query(Notification).filter_by(user_id=outsider.id).one()
    assert notice.title == f"Task reassigned to you: {task.title}" and notice.message == "x" * 280
    assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=task.id, action="update").count() == 1
    tasks.update_task(task.id, TaskUpdate(status="in_progress"), db, outsider)
    assert db.get(Task, task.id).completed_at is None


def test_update_denial_and_commit_failure_preserve_rows(work_case):
    db, manager, recipient, outsider, task = work_case
    with pytest.raises(HTTPException) as exc:
        tasks.update_task(task.id, TaskUpdate(title="Forbidden"), db, recipient)
    assert exc.value.status_code == 403 and task.title != "Forbidden"
    original = task.assigned_to
    def fail(_):
        raise RuntimeError("commit failure")
    event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError, match="commit failure"):
        tasks.update_task(task.id, TaskUpdate(assigned_to=outsider.id), db, manager)
    event.remove(db, "before_commit", fail)
    db.rollback()
    assert db.get(Task, task.id).assigned_to == original
    assert db.query(Notification).filter_by(user_id=outsider.id).count() == 0
    assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=task.id).count() == 0
