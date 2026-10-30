"""User-facing Task COMPLETE endpoint on approved identity-pinned PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from app.api.routes.tasks import router
from app.core.deps import get_current_user, get_db
from app.libs.enums.work_management import TaskStatus
from app.models import audit_service
from app.models.work_management import tasks_service
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def actor(sessions, *, permissions=(), access_policy=None):
    with sessions.begin() as db:
        user = User(
            name="Task COMPLETE actor",
            email=f"task-complete-{uuid4().hex}@example.invalid",
            password_hash="unused-test-value",
            factory_code="MIL",
            extra_permissions=list(permissions),
            access_policy=access_policy,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return int(user.id)


def task_row(sessions, *, creator_id, assigned_to, status="pending", completed_at=None):
    title = f"Task COMPLETE {uuid4().hex}"
    with sessions.begin() as db:
        task = Task(
            title=title,
            description="Task completion fixture",
            created_by=creator_id,
            assigned_to=assigned_to,
            status=status,
            priority="medium",
            entity_type="WorkOrder",
            entity_id=42,
            completed_at=completed_at,
        )
        db.add(task)
        db.flush()
        return int(task.id), task.title


def client_for(sessions, actor_id, *, probe_commit=False):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
            if probe_commit:
                db.info["task_complete_commit_probe"] = True
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, actor_id)
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=False)


def task_snapshot(sessions, task_id):
    with sessions() as db:
        task = db.get(Task, task_id)
        assert task is not None
        values = {column.name: getattr(task, column.name) for column in Task.__table__.columns}
        audits = db.query(AuditLog).filter_by(
            entity_type="Task", entity_id=task_id, action="complete"
        ).order_by(AuditLog.id).all()
        notices = db.query(Notification).filter_by(title=f"Task completed: {task.title}").all()
        return (
            values,
            db.query(Task).count(),
            [(row.user_id, row.old_value_json, row.new_value_json) for row in audits],
            [(row.user_id, row.title, row.message, row.link) for row in notices],
        )


def expected_timestamp(value):
    return value.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize("actor_kind", ["assignee", "manager"])
def test_pg_task_complete_actor_notification_audit_and_shared_session(
    customer_pg_sessions, monkeypatch, actor_kind,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    manager_id = actor(sessions, permissions=["tasks.manage"])
    acting_id = assignee_id if actor_kind == "assignee" else manager_id
    task_id, title = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    with sessions() as db:
        initial_task_count = db.query(Task).count()
    completed_at = datetime(2026, 10, 30, 7, 8, 9, tzinfo=timezone.utc)

    class FixedClock:
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return completed_at

    applied_sessions = []
    notified_sessions = []
    audited_sessions = []
    original_apply = tasks_service.apply_user_task_completion
    original_notify = tasks_service.notify
    original_log = tasks_service.log_action

    def observe_apply(db, row, **kwargs):
        assert object_session(row) is db
        assert row.status != TaskStatus.COMPLETED.value
        applied_sessions.append(db)
        return original_apply(db, row, **kwargs)

    def observe_notify(db, **kwargs):
        notified_sessions.append(db)
        return original_notify(db, **kwargs)

    def observe_audit(db, *args, **kwargs):
        audited_sessions.append(db)
        return original_log(db, *args, **kwargs)

    before_commits = []

    def count_commit(db):
        if db.info.get("task_complete_commit_probe"):
            before_commits.append(db)

    event.listen(Session, "before_commit", count_commit)
    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "datetime", FixedClock)
        patch.setattr(tasks_service, "apply_user_task_completion", observe_apply)
        patch.setattr(tasks_service, "notify", observe_notify)
        patch.setattr(tasks_service, "log_action", observe_audit)
        client = client_for(sessions, acting_id, probe_commit=True)
        try:
            response = client.post(f"/tasks/{task_id}/complete")
        finally:
            client.close()
            event.remove(Session, "before_commit", count_commit)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == task_id and body["status"] == TaskStatus.COMPLETED.value
    assert body["completed_at"] == expected_timestamp(completed_at)
    assert applied_sessions and len(applied_sessions) == 1
    assert notified_sessions == applied_sessions and audited_sessions == applied_sessions
    assert before_commits == applied_sessions
    saved, task_count, audits, notices = task_snapshot(sessions, task_id)
    assert task_count == initial_task_count
    assert saved["status"] == TaskStatus.COMPLETED.value
    assert saved["completed_at"] == completed_at
    assert audits == [(acting_id, None, None)]
    assert notices == [
        (
            creator_id,
            f"Task completed: {title}",
            f"Completed by user #{acting_id}",
            "/work-orders/42",
        )
    ]
    chain(sessions)


@pytest.mark.parametrize("creator_mode", ["same_actor", "missing_creator"])
def test_pg_task_complete_does_not_notify_without_distinct_creator(customer_pg_sessions, creator_mode):
    sessions = customer_pg_sessions
    assignee_id = actor(sessions)
    creator_id = assignee_id if creator_mode == "same_actor" else None
    task_id, _ = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    with client_for(sessions, assignee_id) as client:
        response = client.post(f"/tasks/{task_id}/complete")
    assert response.status_code == 200, response.text
    saved, _, audits, notices = task_snapshot(sessions, task_id)
    assert response.json()["status"] == TaskStatus.COMPLETED.value
    assert saved["status"] == TaskStatus.COMPLETED.value and saved["completed_at"] is not None
    assert audits == [(assignee_id, None, None)]
    assert notices == []
    chain(sessions)


@pytest.mark.parametrize("actor_kind", ["outsider", "denied_manager"])
def test_pg_task_complete_denials_preserve_all_task_effects(customer_pg_sessions, actor_kind):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    task_id, _ = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    denied_manager_id = actor(
        sessions,
        permissions=["*"],
        access_policy={"MIL": {"deny": ["tasks.manage"]}},
    )
    actor_id = actor(sessions) if actor_kind == "outsider" else denied_manager_id
    before = task_snapshot(sessions, task_id)
    with client_for(sessions, actor_id) as client:
        response = client.post(f"/tasks/{task_id}/complete")
    assert response.status_code == 403
    assert response.json() == {"detail": "Only the assignee or a manager may complete this task"}
    assert task_snapshot(sessions, task_id) == before


def test_pg_task_complete_missing_row_precedes_actor_authorization(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = actor(sessions)
    with sessions() as db:
        before = (db.query(Task).count(), db.query(Notification).count(), db.query(AuditLog).count())
    with client_for(sessions, actor_id) as client:
        response = client.post("/tasks/2000000000/complete")
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    with sessions() as db:
        after = (db.query(Task).count(), db.query(Notification).count(), db.query(AuditLog).count())
    assert after == before


@pytest.mark.parametrize(
    "failure_point",
    ["after_notification_flush", "audit_finalize", "before_commit_hook"],
)
def test_pg_task_complete_http_failure_rolls_back_then_fresh_request_retry(
    customer_pg_sessions, monkeypatch, failure_point,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    task_id, title = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    with sessions() as db:
        initial_task_count = db.query(Task).count()
    before = task_snapshot(sessions, task_id)
    original_log = tasks_service.log_action
    reached = []
    flush_witnesses = []

    def fail(*_args, **_kwargs):
        reached.append(failure_point)
        raise RuntimeError(f"injected Task COMPLETE {failure_point}")

    def log_then_fail(db, *args, **kwargs):
        result = original_log(db, *args, **kwargs)
        if failure_point == "after_notification_flush":
            flush_witnesses.append(
                db.query(Notification).filter_by(
                    user_id=creator_id,
                    title=f"Task completed: {title}",
                ).count()
            )
            assert flush_witnesses[-1] == 1
            fail()
        if failure_point == "before_commit_hook":
            event.listen(db, "before_commit", fail)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "log_action", log_then_fail)
        if failure_point == "audit_finalize":
            patch.setattr(audit_service, "add_audit_log_rows", fail)
        with client_for(sessions, assignee_id) as client:
            response = client.post(f"/tasks/{task_id}/complete")
        assert response.status_code == 500
        assert reached == [failure_point]
        if failure_point == "after_notification_flush":
            assert flush_witnesses == [1]
    assert task_snapshot(sessions, task_id) == before

    with client_for(sessions, assignee_id) as client:
        retried = client.post(f"/tasks/{task_id}/complete")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == TaskStatus.COMPLETED.value
    saved, task_count, audits, notices = task_snapshot(sessions, task_id)
    assert task_count == initial_task_count
    assert saved["status"] == TaskStatus.COMPLETED.value and saved["completed_at"] is not None
    assert audits == [(assignee_id, None, None)]
    assert notices == [
        (
            creator_id,
            f"Task completed: {title}",
            f"Completed by user #{assignee_id}",
            "/work-orders/42",
        )
    ]
    chain(sessions)


@pytest.mark.parametrize(
    "failure_point",
    ["after_notification_flush", "audit_finalize", "before_commit_hook"],
)
def test_pg_task_complete_same_session_rollback_clears_audit_state_then_retry(
    customer_pg_sessions, monkeypatch, failure_point,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    task_id, title = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    before = task_snapshot(sessions, task_id)
    original_apply = tasks_service.apply_user_task_completion
    original_notify = tasks_service.notify
    original_log = tasks_service.log_action
    original_add_rows = audit_service.add_audit_log_rows
    reached = []
    apply_sessions = []
    notify_sessions = []
    audit_sessions = []
    notification_flush_witnesses = []
    audit_queue_witnesses = []
    audit_insert_witnesses = []
    audit_finalized_row_witnesses = []
    commit_attempts = []
    injected_commit_hook_witnesses = []
    failure_listener_installed = []

    def fail(*_args, **_kwargs):
        reached.append(failure_point)
        raise RuntimeError(f"injected same-session Task COMPLETE {failure_point}")

    def observe_apply(db, row, **kwargs):
        assert object_session(row) is db
        apply_sessions.append(db)
        return original_apply(db, row, **kwargs)

    def observe_notify(db, **kwargs):
        notify_sessions.append(db)
        result = original_notify(db, **kwargs)
        notification_flush_witnesses.append(
            db.query(Notification).filter_by(
                user_id=creator_id,
                title=f"Task completed: {title}",
            ).count()
        )
        return result

    def observe_audit_rows(db, rows):
        if failure_point == "audit_finalize":
            fail()
        result = original_add_rows(db, rows)
        audit_insert_witnesses.append(len(rows))
        return result

    def fail_after_audit_finalize(db):
        injected_commit_hook_witnesses.append(db)
        audit_finalized_row_witnesses.append(
            db.query(AuditLog).filter_by(
                entity_type="Task", entity_id=task_id, action="complete"
            ).count()
        )
        fail()

    def count_commit(db):
        if db.info.get("task_complete_same_session_probe"):
            commit_attempts.append(db)

    def log_then_inject(db, *args, **kwargs):
        audit_sessions.append(db)
        result = original_log(db, *args, **kwargs)
        transaction = db.get_transaction()
        queued = db.info.get(audit_service._AUDIT_QUEUES, {}).get(transaction, [])
        audit_queue_witnesses.append(
            [(entry.action, entry.entity_type, entry.entity_id) for entry in queued]
        )
        if failure_point == "after_notification_flush":
            assert notification_flush_witnesses == [1]
            assert audit_queue_witnesses == [[("complete", "Task", task_id)]]
            fail()
        if failure_point == "before_commit_hook":
            event.listen(db, "before_commit", fail_after_audit_finalize)
            failure_listener_installed.append(fail_after_audit_finalize)
        return result

    with sessions() as db:
        db.info["task_complete_same_session_probe"] = True
        current = db.get(User, assignee_id)
        task = db.get(Task, task_id)
        assert current is not None and task is not None
        before_commit_count = len(commit_attempts)
        failed_commit_attempts = 0 if failure_point == "after_notification_flush" else 1
        event.listen(Session, "before_commit", count_commit)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(tasks_service, "apply_user_task_completion", observe_apply)
                patch.setattr(tasks_service, "notify", observe_notify)
                patch.setattr(tasks_service, "log_action", log_then_inject)
                patch.setattr(audit_service, "add_audit_log_rows", observe_audit_rows)
                with pytest.raises(RuntimeError, match=f"same-session Task COMPLETE {failure_point}"):
                    tasks_service.complete_user_task(db, current, task_id)

                assert reached == [failure_point]
                assert apply_sessions == notify_sessions == audit_sessions == [db]
                assert notification_flush_witnesses == [1]
                assert audit_queue_witnesses == [[("complete", "Task", task_id)]]
                if failure_point == "before_commit_hook":
                    assert audit_insert_witnesses == [1]
                    assert audit_finalized_row_witnesses == [1]
                    assert commit_attempts == [db]
                    assert injected_commit_hook_witnesses == [db]
                elif failure_point == "audit_finalize":
                    assert audit_insert_witnesses == []
                    assert audit_finalized_row_witnesses == []
                    assert commit_attempts == [db]
                    assert injected_commit_hook_witnesses == []
                else:
                    assert audit_insert_witnesses == []
                    assert audit_finalized_row_witnesses == []
                    assert commit_attempts == []
                    assert injected_commit_hook_witnesses == []

                # The same caller explicitly rolls back the failed attempt and
                # verifies transaction-scoped audit queues/markers were cleared.
                db.rollback()
                for listener in failure_listener_installed:
                    event.remove(db, "before_commit", listener)
                failure_listener_installed.clear()
                db.expire_all()
                rolled_back_task = db.get(Task, task_id)
                assert rolled_back_task is not None
                assert rolled_back_task.status == "pending" and rolled_back_task.completed_at is None
                assert db.query(Notification).filter_by(
                    title=f"Task completed: {title}"
                ).count() == 0
                assert db.query(AuditLog).filter_by(
                    entity_type="Task", entity_id=task_id, action="complete"
                ).count() == 0
                assert db.info.get(audit_service._AUDIT_QUEUES, {}) == {}
                assert not db.info.get(audit_service._AUDIT_COMMITTED, set())
                assert not db.info.get(audit_service._AUDIT_ROLLED_BACK, set())
                assert not db.info.get(audit_service._AUDIT_FINALIZED, set())

            # Retry through the same service on the same Session and actor
            # identity after rollback; no new Session is created between tries.
            completed = tasks_service.complete_user_task(db, current, task_id)
            assert completed is task and object_session(completed) is db
            assert len(commit_attempts) == before_commit_count + failed_commit_attempts + 1
            assert completed.status == TaskStatus.COMPLETED.value
            assert completed.completed_at is not None
            assert db.query(Notification).filter_by(
                user_id=creator_id,
                title=f"Task completed: {title}",
            ).count() == 1
            assert db.query(AuditLog).filter_by(
                entity_type="Task", entity_id=task_id, action="complete"
            ).count() == 1
            assert db.info.get(audit_service._AUDIT_QUEUES, {}) == {}
            assert not db.info.get(audit_service._AUDIT_COMMITTED, set())
            assert not db.info.get(audit_service._AUDIT_ROLLED_BACK, set())
            assert not db.info.get(audit_service._AUDIT_FINALIZED, set())
        finally:
            for listener in failure_listener_installed:
                event.remove(db, "before_commit", listener)
            event.remove(Session, "before_commit", count_commit)

    saved, task_count, audits, notices = task_snapshot(sessions, task_id)
    assert task_count == before[1]
    assert saved["status"] == TaskStatus.COMPLETED.value and saved["completed_at"] is not None
    assert audits == [(assignee_id, None, None)]
    assert notices == [
        (
            creator_id,
            f"Task completed: {title}",
            f"Completed by user #{assignee_id}",
            "/work-orders/42",
        )
    ]
    chain(sessions)


def test_pg_task_complete_repeat_resets_timestamp_and_duplicates_notice_and_audit(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    task_id, title = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    with sessions() as db:
        initial_task_count = db.query(Task).count()
    first_time = datetime(2026, 10, 30, 9, 10, 11, tzinfo=timezone.utc)
    second_time = datetime(2026, 10, 30, 9, 10, 12, tzinfo=timezone.utc)

    class SequenceClock:
        instants = iter((first_time, second_time))

        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            return next(cls.instants)

    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "datetime", SequenceClock)
        with client_for(sessions, assignee_id) as client:
            first = client.post(f"/tasks/{task_id}/complete")
            second = client.post(f"/tasks/{task_id}/complete")
    assert first.status_code == second.status_code == 200
    assert first.json()["completed_at"] == expected_timestamp(first_time)
    assert second.json()["completed_at"] == expected_timestamp(second_time)
    saved, task_count, audits, notices = task_snapshot(sessions, task_id)
    assert task_count == initial_task_count
    assert saved["completed_at"] == second_time
    assert audits == [(assignee_id, None, None), (assignee_id, None, None)]
    assert notices == [
        (creator_id, f"Task completed: {title}", f"Completed by user #{assignee_id}", "/work-orders/42"),
        (creator_id, f"Task completed: {title}", f"Completed by user #{assignee_id}", "/work-orders/42"),
    ]
    chain(sessions)


def test_pg_task_complete_concurrent_calls_remain_distinct_without_deduplication(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    assignee_id = actor(sessions)
    manager_id = actor(sessions, permissions=["tasks.manage"])
    task_id, title = task_row(sessions, creator_id=creator_id, assigned_to=assignee_id)
    with sessions() as db:
        initial_task_count = db.query(Task).count()

    barrier = Barrier(2, timeout=8)
    guard = Lock()
    request_sessions = []
    rows_at_boundary = []
    original_apply = tasks_service.apply_user_task_completion

    def wait_after_load_and_authorization(db, row, **kwargs):
        assert object_session(row) is db
        assert row.status == "pending" and row.completed_at is None
        with guard:
            request_sessions.append(db)
            rows_at_boundary.append(row)
        barrier.wait()
        return original_apply(db, row, **kwargs)

    monkeypatch.setattr(tasks_service, "apply_user_task_completion", wait_after_load_and_authorization)

    def complete_as(actor_id):
        with client_for(sessions, actor_id) as client:
            return client.post(f"/tasks/{task_id}/complete")

    with ThreadPoolExecutor(max_workers=2) as pool:
        assignee_future = pool.submit(complete_as, assignee_id)
        manager_future = pool.submit(complete_as, manager_id)
        assignee_response = assignee_future.result(timeout=30)
        manager_response = manager_future.result(timeout=30)

    assert assignee_response.status_code == manager_response.status_code == 200
    assert assignee_response.json()["status"] == manager_response.json()["status"] == TaskStatus.COMPLETED.value
    assert assignee_response.json()["completed_at"] and manager_response.json()["completed_at"]
    assert len(request_sessions) == len({id(db) for db in request_sessions}) == 2
    assert len(rows_at_boundary) == 2 and rows_at_boundary[0] is not rows_at_boundary[1]
    saved, task_count, audits, notices = task_snapshot(sessions, task_id)
    assert saved["status"] == TaskStatus.COMPLETED.value and saved["completed_at"] is not None
    assert task_count == initial_task_count
    assert audits == [(assignee_id, None, None), (manager_id, None, None)] or audits == [
        (manager_id, None, None), (assignee_id, None, None)
    ]
    assert len(notices) == 2
    assert {notice[0] for notice in notices} == {creator_id}
    assert {notice[2] for notice in notices} == {
        f"Completed by user #{assignee_id}",
        f"Completed by user #{manager_id}",
    }
    assert all(notice[1] == f"Task completed: {title}" and notice[3] == "/work-orders/42" for notice in notices)
    chain(sessions)
