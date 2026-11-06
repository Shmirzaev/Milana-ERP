"""Existing operation success, permission and transaction contract on both databases."""
import pytest
from fastapi import HTTPException
from sqlalchemy import event
from app.api.routes import tasks
from app.schemas import AuditLog, Notification, Task
from app.tests.test_work_update_characterization import work_case as work_case, broadcast_sessions as broadcast_sessions


def test_complete_persists_expected_effects(work_case):
    db, manager, recipient, outsider, task = work_case
    before = db.query(Notification).count()
    result = tasks.complete_task(task.id, db, recipient)
    assert result.status == "completed" and result.completed_at is not None
    notice = db.query(Notification).filter_by(user_id=manager.id).one()
    assert notice.title == f"Task completed: {task.title}" and notice.message == f"Completed by user #{recipient.id}"
    assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=task.id, action="complete").count() == 1


def test_complete_refusal_and_failure_are_atomic(work_case):
    db, manager, recipient, outsider, task = work_case
    tid = task.id
    before = db.query(Notification).count()
    with pytest.raises(HTTPException) as exc:
        tasks.complete_task(task.id, db, outsider)
    assert exc.value.status_code == 403
    def fail(_):
        raise RuntimeError("commit failure")
    event.listen(db, "before_commit", fail)
    with pytest.raises(RuntimeError, match="commit failure"):
        tasks.complete_task(task.id, db, recipient)
    event.remove(db, "before_commit", fail)
    db.rollback()
    assert db.get(Task, tid).status == "pending"
    assert db.query(Notification).count() == before
    assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=tid).count() == 0
