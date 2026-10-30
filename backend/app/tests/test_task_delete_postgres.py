"""Approved PostgreSQL coverage for user-facing Task DELETE."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import tasks as tasks_route
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from app.api.routes.tasks import router
from app.core.deps import get_current_user, get_db
from app.models import audit_service
from app.models.work_management import tasks_service
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def _actor(sessions, *, permissions=(), access_policy=None):
    with sessions.begin() as db:
        user = User(
            name="Task DELETE actor",
            email=f"task-delete-{uuid4().hex}@example.invalid",
            password_hash="unused-test-value",
            factory_code="MIL",
            extra_permissions=list(permissions),
            access_policy=access_policy,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return int(user.id)


def _task(sessions, *, creator_id, assigned_to, status="pending"):
    title = f"Task DELETE {uuid4().hex}"
    with sessions.begin() as db:
        row = Task(
            title=title,
            description="Task deletion fixture",
            created_by=creator_id,
            assigned_to=assigned_to,
            status=status,
            priority="medium",
            entity_type="WorkOrder",
            entity_id=42,
        )
        db.add(row)
        db.flush()
        task_id = int(row.id)
        db.add(Notification(
            user_id=assigned_to,
            title=f"New task: {title}",
            message="Existing notice retained by Task DELETE",
            link="/work-orders/42",
            is_read=False,
        ))
    return task_id, title, f"New task: {title}"


def _client(sessions, actor_id, *, probe_commit=False, raise_server_exceptions=False):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
            if probe_commit:
                db.info["task_delete_commit_probe"] = True
            yield db

    def current_user():
        with sessions() as db:
            user = db.get(User, actor_id)
            assert user is not None
            db.expunge(user)
            return user

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _snapshot_in_session(db, task_id, notice_title):
    row = db.get(Task, task_id)
    task_values = None if row is None else tuple(
        (column.name, getattr(row, column.name)) for column in Task.__table__.columns
    )
    notices = db.query(Notification).filter_by(title=notice_title).order_by(Notification.id).all()
    notice_values = tuple(
        (item.user_id, item.title, item.message, item.link, item.is_read, item.created_at)
        for item in notices
    )
    audits = (
        db.query(AuditLog)
        .filter_by(entity_type="Task", entity_id=task_id)
        .order_by(AuditLog.id)
        .all()
    )
    audit_values = tuple(
        (item.user_id, item.action, item.old_value_json, item.new_value_json,
         item.prev_hash, item.entry_hash)
        for item in audits
    )
    return task_values, notice_values, audit_values


def _snapshot(sessions, task_id, notice_title):
    with sessions() as db:
        return _snapshot_in_session(db, task_id, notice_title)


@pytest.mark.parametrize(
    "actor_kind,status",
    [
        ("creator", "pending"),
        ("creator_with_manager_denied", "completed"),
        ("manager", "cancelled"),
    ],
)
def test_pg_task_delete_creator_and_manager_share_session_audit_and_keep_notice(
    customer_pg_sessions, monkeypatch, actor_kind, status,
):
    sessions = customer_pg_sessions
    creator_id = _actor(sessions)
    assignee_id = _actor(sessions)
    manager_id = _actor(sessions, permissions=["tasks.manage"])
    denied_creator_id = _actor(
        sessions,
        permissions=["*"],
        access_policy={"MIL": {"deny": ["tasks.manage"]}},
    )
    task_creator = denied_creator_id if actor_kind == "creator_with_manager_denied" else creator_id
    actor_id = {
        "creator": creator_id,
        "creator_with_manager_denied": denied_creator_id,
        "manager": manager_id,
    }[actor_kind]
    task_id, _title, notice_title = _task(
        sessions, creator_id=task_creator, assigned_to=assignee_id, status=status,
    )
    before = _snapshot(sessions, task_id, notice_title)
    with sessions() as db:
        before_task_count = db.query(Task).count()

    deleted_sessions = []
    audit_sessions = []
    before_commits = []
    original_delete = tasks_service.delete_user_task_row
    original_log = tasks_service.log_action

    def observe_delete(db, row):
        assert object_session(row) is db
        deleted_sessions.append(db)
        return original_delete(db, row)

    def observe_audit(db, *args, **kwargs):
        audit_sessions.append(db)
        return original_log(db, *args, **kwargs)

    def count_commit(db):
        if db.info.get("task_delete_commit_probe"):
            before_commits.append(db)

    event.listen(Session, "before_commit", count_commit)
    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "delete_user_task_row", observe_delete)
        patch.setattr(tasks_service, "log_action", observe_audit)
        client = _client(sessions, actor_id, probe_commit=True)
        try:
            response = client.delete(f"/tasks/{task_id}")
        finally:
            client.close()
            event.remove(Session, "before_commit", count_commit)

    assert response.status_code == 204
    assert response.content == b""
    assert deleted_sessions and len(deleted_sessions) == 1
    assert audit_sessions == deleted_sessions
    assert before_commits == deleted_sessions
    after = _snapshot(sessions, task_id, notice_title)
    assert after[0] is None
    assert after[1] == before[1]
    assert len(after[2]) == 1
    audit = after[2][0]
    assert audit[:4] == (actor_id, "delete", None, None)
    assert audit[4] is None or len(audit[4]) == 64
    assert len(audit[5]) == 64
    with sessions() as db:
        assert db.query(Task).count() == before_task_count - 1
    chain(sessions)


@pytest.mark.parametrize("actor_kind", ["assignee", "outsider", "denied_manager"])
def test_pg_task_delete_denials_preserve_task_notice_audit_and_commit_state(
    customer_pg_sessions, actor_kind,
):
    sessions = customer_pg_sessions
    creator_id = _actor(sessions)
    assignee_id = _actor(sessions)
    task_id, _title, notice_title = _task(
        sessions, creator_id=creator_id, assigned_to=assignee_id,
    )
    denied_manager_id = _actor(
        sessions,
        permissions=["*"],
        access_policy={"MIL": {"deny": ["tasks.manage"]}},
    )
    actor_id = {
        "assignee": assignee_id,
        "outsider": _actor(sessions),
        "denied_manager": denied_manager_id,
    }[actor_kind]
    before = _snapshot(sessions, task_id, notice_title)
    before_commits = []

    def count_commit(db):
        if db.info.get("task_delete_commit_probe"):
            before_commits.append(db)

    event.listen(Session, "before_commit", count_commit)
    client = _client(sessions, actor_id, probe_commit=True)
    try:
        response = client.delete(f"/tasks/{task_id}")
    finally:
        client.close()
        event.remove(Session, "before_commit", count_commit)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only managers or task creator may delete"}
    assert _snapshot(sessions, task_id, notice_title) == before
    assert before_commits == []
    chain(sessions)


def test_pg_task_delete_missing_row_precedes_authorization_without_writes(customer_pg_sessions):
    sessions = customer_pg_sessions
    outsider_id = _actor(sessions)
    with sessions() as db:
        before = (db.query(Task).count(), db.query(Notification).count(), db.query(AuditLog).count())
    client = _client(sessions, outsider_id, probe_commit=True)
    try:
        response = client.delete("/tasks/2000000000")
    finally:
        client.close()
    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found"}
    with sessions() as db:
        after = (db.query(Task).count(), db.query(Notification).count(), db.query(AuditLog).count())
    assert after == before


@pytest.mark.parametrize(
    "failure_point",
    ["after_delete_flush", "audit_finalize", "before_commit_hook"],
)
def test_pg_task_delete_failure_rolls_back_and_retries_on_same_session(
    customer_pg_sessions, monkeypatch, failure_point,
):
    sessions = customer_pg_sessions
    creator_id = _actor(sessions)
    assignee_id = _actor(sessions)
    manager_id = _actor(sessions, permissions=["tasks.manage"])
    task_id, _title, notice_title = _task(
        sessions, creator_id=creator_id, assigned_to=assignee_id,
    )
    before = _snapshot(sessions, task_id, notice_title)
    witnessed = []
    committed_sessions = []
    fired = False

    with sessions() as db:
        manager = db.get(User, manager_id)
        assert manager is not None
        event.listen(db, "after_commit", lambda session: committed_sessions.append(session))
        original_log = tasks_service.log_action
        original_finalize = audit_service._finalize_postgres_audits

        def fail_after_delete_flush(session, *args, **kwargs):
            result = original_log(session, *args, **kwargs)
            assert session.query(Task).filter_by(id=task_id).count() == 0
            assert session.info.get("audit.chain.queues")
            nonlocal fired
            if not fired:
                fired = True
                witnessed.append(("after_delete_flush", session))
                raise RuntimeError("injected Task DELETE after mapped-row flush")
            return result

        def fail_after_audit_finalize(session):
            result = original_finalize(session)
            assert session.query(Task).filter_by(id=task_id).count() == 0
            rows = session.query(AuditLog).filter_by(
                entity_type="Task", entity_id=task_id, action="delete",
            ).all()
            assert len(rows) == 1 and rows[0].entry_hash
            nonlocal fired
            if not fired:
                fired = True
                witnessed.append(("audit_finalize", session))
                raise RuntimeError("injected Task DELETE after audit finalization")
            return result

        def fail_before_commit(session):
            nonlocal fired
            if session is db and not fired:
                assert session.query(Task).filter_by(id=task_id).count() == 0
                assert session.info.get("audit.chain.queues")
                witnessed.append(("before_commit_hook", session))
                fired = True
                raise RuntimeError("injected Task DELETE before outer commit")

        with monkeypatch.context() as patch:
            if failure_point == "after_delete_flush":
                patch.setattr(tasks_service, "log_action", fail_after_delete_flush)
            elif failure_point == "audit_finalize":
                patch.setattr(audit_service, "_finalize_postgres_audits", fail_after_audit_finalize)
            else:
                # Match the production listener order: the deferred audit
                # finalizer runs before this later outer-commit fault hook.
                audit_service._install_postgres_audit_hooks(db)
                event.listen(db, "before_commit", fail_before_commit)

            with pytest.raises(RuntimeError, match="injected Task DELETE"):
                tasks_service.delete_user_task(db, manager, task_id)
            db.rollback()
            assert db.query(Task).filter_by(id=task_id).one_or_none() is not None
            assert not db.info.get("audit.chain.queues", {})
            assert not db.info.get("audit.chain.committed", set())
            assert not db.info.get("audit.chain.rolled_back", set())
            assert not committed_sessions

            assert tasks_service.delete_user_task(db, manager, task_id) is None
            assert committed_sessions == [db]

        if failure_point == "before_commit_hook":
            event.remove(db, "before_commit", fail_before_commit)

    assert witnessed == [(failure_point, db)]
    after = _snapshot(sessions, task_id, notice_title)
    assert after[0] is None
    assert after[1] == before[1]
    assert len(after[2]) == 1
    audit = after[2][0]
    assert audit[0:4] == (manager_id, "delete", None, None)
    assert len(audit[5]) == 64
    chain(sessions)


def test_pg_task_delete_two_authorized_sessions_keep_current_duplicate_request_semantics(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    creator_id = _actor(sessions)
    assignee_id = _actor(sessions)
    manager_ids = [
        _actor(sessions, permissions=["tasks.manage"]),
        _actor(sessions, permissions=["tasks.manage"]),
    ]
    task_id, _title, notice_title = _task(
        sessions, creator_id=creator_id, assigned_to=assignee_id,
    )
    barrier = Barrier(2)
    arrived = []
    outcomes = []
    original_delete = tasks_service.delete_user_task_row
    original_service_delete = tasks_route.delete_user_task

    def wait_after_preflight(db, row):
        assert object_session(row) is db
        arrived.append(db)
        barrier.wait(timeout=8)
        return original_delete(db, row)

    def observe_request_delete(db, actor, requested_task_id):
        outcome = {"actor_id": int(actor.id), "session": db, "commits": 0}
        event.listen(db, "after_commit", lambda committed: outcome.__setitem__("commits", outcome["commits"] + 1))
        try:
            result = original_service_delete(db, actor, requested_task_id)
        except Exception as exc:
            outcome["exception"] = type(exc).__name__
            raise
        outcome["audit_rows"] = tuple(
            (audit.user_id, audit.action, audit.entity_type, audit.entity_id,
             audit.old_value_json, audit.new_value_json, audit.entry_hash)
            for audit in db.query(AuditLog)
            .filter_by(user_id=actor.id, action="delete", entity_type="Task", entity_id=task_id)
            .order_by(AuditLog.id)
            .all()
        )
        outcomes.append(outcome)
        return result

    def delete_once(actor_id):
        with _client(sessions, actor_id, raise_server_exceptions=True) as client:
            return client.delete(f"/tasks/{task_id}").status_code

    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "delete_user_task_row", wait_after_preflight)
        patch.setattr(tasks_route, "delete_user_task", observe_request_delete)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(delete_once, actor_id) for actor_id in manager_ids]
            statuses = sorted(future.result(timeout=20) for future in futures)

    assert len(arrived) == 2
    assert statuses == [204, 204]
    assert len(outcomes) == 2
    assert {outcome["actor_id"] for outcome in outcomes} == set(manager_ids)
    assert len({id(outcome["session"]) for outcome in outcomes}) == 2
    assert all(outcome["commits"] == 1 and "exception" not in outcome for outcome in outcomes)
    for outcome in outcomes:
        assert len(outcome["audit_rows"]) == 1
        audit = outcome["audit_rows"][0]
        assert audit[:6] == (outcome["actor_id"], "delete", "Task", task_id, None, None)
        assert len(audit[6]) == 64
    task_values, notices, audits = _snapshot(sessions, task_id, notice_title)
    assert task_values is None
    assert notices[0][1] == notice_title
    assert len(audits) == 2
    assert all(row[1] == "delete" and row[2] is None and row[3] is None for row in audits)
    chain(sessions)
