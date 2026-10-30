"""Approved disposable-PostgreSQL coverage for user-facing Task CREATE."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import object_session

from app.api.routes import tasks as task_routes
from app.libs.dto.work_management.tasks import TaskIn
from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.models import audit_service
from app.models.work_management import tasks_service
from app.models.work_management.tasks_service import TaskCreateRefused
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions as customer_pg_sessions  # noqa: F401


def _actor(sessions, *, manager=False, active=True):
    with sessions.begin() as db:
        actor = User(
            name="Task CREATE PostgreSQL actor",
            email=f"task-create-{uuid4().hex}@example.invalid",
            password_hash="unused-pg-test",
            factory_code="MIL",
            extra_permissions=["tasks.manage"] if manager else [],
            is_active=active,
        )
        db.add(actor)
        db.flush()
        return actor.id


def _deactivate_existing_users(sessions):
    """Keep broadcast assertions scoped to actors created by that case."""
    with sessions.begin() as db:
        db.query(User).update({"is_active": False}, synchronize_session=False)


def _load_actor(db, actor_id):
    actor = db.get(User, actor_id)
    assert actor is not None
    return actor


def _counts(db):
    return {
        "tasks": db.query(Task).count(),
        "notifications": db.query(Notification).count(),
        "audits": db.query(AuditLog).count(),
    }


def test_pg_task_create_self_and_single_assignment_share_session_and_audit(customer_pg_sessions):
    sessions = customer_pg_sessions
    creator_id = _actor(sessions, manager=True)
    target_id = _actor(sessions)
    title = f"Task create {uuid4().hex}"

    with sessions() as db:
        creator = _load_actor(db, creator_id)
        before = _counts(db)
        commits = []
        def committed(session):
            commits.append(session)
        event.listen(db, "after_commit", committed)
        try:
            self_task = tasks_service.create_user_task(
                db,
                creator,
                TaskIn.model_validate({"title": title + " self", "status": "in_progress", "priority": "urgent"}),
            )
            assert len(commits) == 1 and commits[0] is db
        finally:
            event.remove(db, "after_commit", committed)
        assert object_session(self_task) is db
        assert self_task.assigned_to == creator_id and self_task.created_by == creator_id
        assert self_task.status == TaskStatus.IN_PROGRESS.value
        assert self_task.priority == TaskPriority.URGENT.value
        assert _counts(db) == {"tasks": before["tasks"] + 1,
                               "notifications": before["notifications"],
                               "audits": before["audits"] + 1}

        commits = []
        event.listen(db, "after_commit", committed)
        try:
            assigned = tasks_service.create_user_task(
                db,
                creator,
                TaskIn.model_validate({"title": title + " assigned", "assigned_to": target_id,
                                       "description": "x" * 300, "entity_type": "shipment", "entity_id": 9}),
            )
            assert len(commits) == 1 and commits[0] is db
        finally:
            event.remove(db, "after_commit", committed)
        assert object_session(assigned) is db
        assert assigned.assigned_to == target_id and assigned.created_by == creator_id
        notice = db.query(Notification).filter_by(user_id=target_id, title=f"New task: {title} assigned").one()
        assert notice.message == "x" * 280 and notice.link == "/shipments"
        audit = db.query(AuditLog).filter_by(entity_type="Task", entity_id=assigned.id, action="create").one()
        assert audit.user_id == creator_id

    chain(sessions)


def test_pg_task_broadcast_is_bounded_active_ordered_and_atomic(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "4")
    _deactivate_existing_users(sessions)
    manager_id = _actor(sessions, manager=True)
    active_ids = [manager_id, _actor(sessions), _actor(sessions), _actor(sessions)]
    _actor(sessions, active=False)
    title = f"Task broadcast {uuid4().hex}"

    with sessions() as db:
        manager = _load_actor(db, manager_id)
        before = _counts(db)
        first = tasks_service.create_user_task(
            db,
            manager,
            TaskIn.model_validate({"title": title, "assigned_to": -1, "description": "z" * 300,
                                   "entity_type": "invoice", "entity_id": 21}),
        )
        assert object_session(first) is db
        tasks = db.query(Task).filter_by(title=title).order_by(Task.id).all()
        notices = db.query(Notification).filter_by(title=f"New task: {title}").order_by(Notification.user_id).all()
        assert [row.assigned_to for row in tasks] == sorted(active_ids)
        assert [row.user_id for row in notices] == sorted(active_ids)
        assert all(row.created_by == manager_id and row.status == "pending" and row.priority == "medium" for row in tasks)
        assert all(row.message == "z" * 280 and row.link == "/finance" for row in notices)
        assert first.id == tasks[0].id
        audit = db.query(AuditLog).filter_by(entity_type="Task", entity_id=first.id, action="create").one()
        assert audit.user_id == manager_id
        assert audit.new_value_json == {"title": title, "assigned_to": "everyone", "created_count": 4}
        assert _counts(db) == {"tasks": before["tasks"] + 4,
                               "notifications": before["notifications"] + 4,
                               "audits": before["audits"] + 1}

        before_refusal = _counts(db)
        monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "3")
        with pytest.raises(TaskCreateRefused) as refused:
            tasks_service.create_user_task(db, manager, TaskIn.model_validate({"title": title + " over", "assigned_to": -1}))
        assert refused.value.reason == "recipient_limit_exceeded"
        assert _counts(db) == before_refusal

    chain(sessions)


def test_pg_task_create_denials_leave_no_task_notification_or_audit(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions)
    target_id = _actor(sessions)
    title = f"Denied task {uuid4().hex}"
    with sessions() as db:
        actor = _load_actor(db, actor_id)
        before = _counts(db)
        with pytest.raises(TaskCreateRefused) as denied_assignment:
            tasks_service.create_user_task(db, actor, TaskIn.model_validate({"title": title, "assigned_to": target_id}))
        assert denied_assignment.value.reason == "manager_required"
        with pytest.raises(TaskCreateRefused) as denied_broadcast:
            tasks_service.create_user_task(db, actor, TaskIn.model_validate({"title": title, "assigned_to": -1}))
        assert denied_broadcast.value.reason == "manager_required"
        assert _counts(db) == before
        assert not db.new


@pytest.mark.parametrize(("mode", "failure_point"), [
    ("assigned", "notification_after_flush"),
    ("broadcast", "notification_after_flush"),
    ("self", "audit_commit"),
    ("assigned", "audit_commit"),
    ("broadcast", "audit_commit"),
])
def test_pg_task_create_failure_after_flush_or_audit_commit_rolls_back_then_retry(
    customer_pg_sessions, monkeypatch, mode, failure_point,
):
    sessions = customer_pg_sessions
    if mode == "broadcast":
        _deactivate_existing_users(sessions)
    manager_id = _actor(sessions, manager=True)
    target_id = _actor(sessions)
    title = f"Retry task {uuid4().hex} {mode} {failure_point}"
    assigned_to = {"self": manager_id, "assigned": target_id, "broadcast": -1}[mode]
    payload = TaskIn.model_validate({"title": title, "assigned_to": assigned_to})
    expected_tasks = 2 if mode == "broadcast" else 1
    expected_notices = {"self": 0, "assigned": 1, "broadcast": 2}[mode]

    with sessions() as db:
        manager = _load_actor(db, manager_id)
        before = _counts(db)

        with monkeypatch.context() as patch:
            if failure_point == "notification_after_flush":
                if mode == "assigned":
                    original_notify = tasks_service.notify

                    def fail_after_single_notification(session, **kwargs):
                        notification = original_notify(session, **kwargs)
                        assert notification.id is not None
                        assert session.query(Task).filter_by(title=title).count() == 1
                        assert session.query(Notification).filter_by(title=f"New task: {title}").count() == 1
                        raise RuntimeError("Synthetic Task notification failure after flush")

                    patch.setattr(tasks_service, "notify", fail_after_single_notification)
                else:
                    original_notify_many = tasks_service.notify_many

                    def fail_after_broadcast_flush(session, **kwargs):
                        notifications = original_notify_many(session, **kwargs)
                        assert all(notification.id is not None for notification in notifications)
                        assert session.query(Task).filter_by(title=title).count() == expected_tasks
                        assert session.query(Notification).filter_by(title=f"New task: {title}").count() == expected_notices
                        raise RuntimeError("Synthetic Task broadcast notification failure after flush")

                    patch.setattr(tasks_service, "notify_many", fail_after_broadcast_flush)
                error_text = "Synthetic Task .*notification failure after flush"
            else:
                def fail_hash(**_kwargs):
                    raise RuntimeError("Synthetic Task audit-chain finalization failure")

                patch.setattr(audit_service, "_audit_entry_hash", fail_hash)
                error_text = "Synthetic Task audit-chain finalization failure"

            with pytest.raises(RuntimeError, match=error_text):
                tasks_service.create_user_task(db, manager, payload)
            db.rollback()

        assert _counts(db) == before
        assert not db.new
        retry = task_routes.create_task(payload, db, manager)
        assert retry.id is not None
        assert db.query(Task).filter_by(title=title).count() == expected_tasks
        assert db.query(Notification).filter_by(title=f"New task: {title}").count() == expected_notices
        assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=retry.id, action="create").count() == 1

    chain(sessions)


def test_pg_repeated_identical_task_create_requests_remain_distinct(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions)
    payload = TaskIn.model_validate({"title": f"Repeated request {uuid4().hex}", "assigned_to": actor_id})
    with sessions() as db:
        actor = _load_actor(db, actor_id)
        first = task_routes.create_task(payload, db, actor)
        second = task_routes.create_task(payload, db, actor)
        assert first.id != second.id
        assert db.query(Task).filter_by(title=payload.title).count() == 2
        assert db.query(Notification).filter_by(title=f"New task: {payload.title}").count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Task",
                                         AuditLog.entity_id.in_((first.id, second.id)),
                                         AuditLog.action == "create").count() == 2
    chain(sessions)


def test_pg_task_broadcast_refuses_when_authenticated_actor_becomes_inactive_before_recipient_select(
    customer_pg_sessions,
):
    from fastapi import HTTPException

    sessions = customer_pg_sessions
    manager_id = _actor(sessions, manager=True)
    title = f"No active broadcast recipients {uuid4().hex}"

    with sessions() as db:
        # The current-user object represents an actor authenticated while
        # active. Deactivate every persisted user after that read, leaving the
        # request's already-resolved actor object intact for this race case.
        manager = _load_actor(db, manager_id)
        assert manager.is_active is True
        db.query(User).update({"is_active": False}, synchronize_session=False)
        db.commit()
        assert manager.is_active is True
        before = _counts(db)
        commits = []

        def record_commit(session):
            commits.append(session)

        event.listen(db, "after_commit", record_commit)
        try:
            with pytest.raises(HTTPException) as refused:
                task_routes.create_task(
                    TaskIn.model_validate({"title": title, "assigned_to": -1}), db, manager
                )
        finally:
            event.remove(db, "after_commit", record_commit)

        assert refused.value.status_code == 404
        assert refused.value.detail == "No active users found"
        assert _counts(db) == before
        assert not db.new and commits == []


def test_pg_concurrent_task_creates_keep_audit_chain(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = _actor(sessions)
    marker = uuid4().hex
    start = Barrier(3)

    def worker(index):
        with sessions() as db:
            actor = _load_actor(db, actor_id)
            start.wait(timeout=10)
            row = tasks_service.create_user_task(
                db, actor, TaskIn.model_validate({"title": f"Concurrent task {marker} {index}"})
            )
            return row.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        start.wait(timeout=10)
        ids = [future.result(timeout=30) for future in futures]
    assert len(set(ids)) == 2
    with sessions() as db:
        assert db.query(Task).filter(Task.id.in_(ids)).count() == 2
        assert db.query(Notification).filter(Notification.title.like(f"New task: Concurrent task {marker}%")).count() == 0
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Task", AuditLog.entity_id.in_(ids),
                                         AuditLog.action == "create").count() == 2
    chain(sessions)
