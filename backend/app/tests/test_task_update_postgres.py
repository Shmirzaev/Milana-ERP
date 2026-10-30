"""User-facing Task PATCH on the approved identity-pinned PostgreSQL target."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from app.api.routes.tasks import router
from app.core.deps import get_current_user, get_db
from app.libs.enums.work_management import TaskPriority, TaskStatus
from app.models import audit_service
from app.models.work_management import tasks_service
from app.schemas import AuditLog, Notification, Task, User
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


def actor(sessions, *, permissions=(), active=True, access_policy=None):
    with sessions.begin() as db:
        user = User(
            name="Task PATCH actor",
            email=f"task-patch-{uuid4().hex}@example.invalid",
            password_hash="unused-test-value",
            factory_code="MIL",
            extra_permissions=list(permissions),
            access_policy=access_policy,
            is_active=active,
        )
        db.add(user)
        db.flush()
        return int(user.id)


def task_row(sessions, *, creator_id, assigned_to, marker=None, status="pending", completed_at=None):
    marker = marker or uuid4().hex
    with sessions.begin() as db:
        task = Task(
            title=f"Task PATCH {marker}",
            description="Original description",
            created_by=creator_id,
            assigned_to=assigned_to,
            status=status,
            priority="medium",
            due_date=datetime(2026, 11, 15, tzinfo=timezone.utc),
            entity_type="WorkOrder",
            entity_id=42,
            completed_at=completed_at,
        )
        db.add(task)
        db.flush()
        return int(task.id), task.title


def client_for(sessions, actor_id):
    app = FastAPI()
    app.include_router(router)

    def isolated_db():
        with sessions() as db:
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
        audits = db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id, action="update").all()
        notices = db.query(Notification).filter_by(
            title=f"Task reassigned to you: {task.title}"
        ).all()
        return values, [(row.user_id, row.old_value_json, row.new_value_json) for row in audits], [
            (row.user_id, row.title, row.message, row.link) for row in notices
        ]


def test_pg_task_patch_reassignment_notification_audit_and_shared_session(
    customer_pg_sessions, monkeypatch,
):
    sessions = customer_pg_sessions
    manager_id = actor(sessions, permissions=["tasks.manage"])
    previous_assignee = actor(sessions)
    next_assignee = actor(sessions)
    task_id, title = task_row(sessions, creator_id=manager_id, assigned_to=previous_assignee)
    marker = uuid4().hex
    title = f"Task PATCH updated {marker}"
    payload = {
        "title": title,
        "description": "x" * 300,
        "assigned_to": next_assignee,
        "status": "completed",
        "priority": "urgent",
        "entity_type": "WorkOrder",
        "entity_id": 42,
    }
    applied_sessions = []
    notified_sessions = []
    audited_sessions = []
    original_apply = tasks_service.apply_user_task_update
    original_notify = tasks_service.notify
    original_log = tasks_service.log_action

    def observe_apply(db, row, command, **kwargs):
        assert object_session(row) is db
        assert command.present_fields == frozenset(payload)
        assert command.status is TaskStatus.COMPLETED
        assert command.priority is TaskPriority.URGENT
        assert isinstance(command.status, TaskStatus) and isinstance(command.priority, TaskPriority)
        applied_sessions.append(db)
        return original_apply(db, row, command, **kwargs)

    def observe_notify(db, **kwargs):
        notified_sessions.append(db)
        return original_notify(db, **kwargs)

    def observe_audit(db, *args, **kwargs):
        audited_sessions.append(db)
        return original_log(db, *args, **kwargs)

    before_commits = []

    def count_commit(db):
        if db.info.get("task_patch_probe"):
            before_commits.append(db)

    event.listen(Session, "before_commit", count_commit)

    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "apply_user_task_update", observe_apply)
        patch.setattr(tasks_service, "notify", observe_notify)
        patch.setattr(tasks_service, "log_action", observe_audit)
        # Mark only the request-owned Session without changing its lifecycle.
        def probed_db():
            with sessions() as db:
                db.info["task_patch_probe"] = True
                yield db

        app_client = client_for(sessions, manager_id)
        app_client.app.dependency_overrides[get_db] = probed_db
        try:
            response = app_client.patch(f"/tasks/{task_id}", json=payload)
        finally:
            app_client.close()
            event.remove(Session, "before_commit", count_commit)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == task_id and body["title"] == title
    assert body["status"] == "completed" and body["priority"] == "urgent"
    assert body["assigned_to"] == next_assignee and body["completed_at"]
    assert applied_sessions and len(applied_sessions) == 1
    assert notified_sessions == applied_sessions and audited_sessions == applied_sessions
    assert before_commits == applied_sessions
    with sessions() as db:
        saved = db.get(Task, task_id)
        assert saved is not None and saved.status == "completed" and saved.priority == "urgent"
        notification = db.query(Notification).filter_by(
            user_id=next_assignee, title=f"Task reassigned to you: {title}"
        ).one()
        assert notification.message == "x" * 280
        assert notification.link == "/work-orders/42"
        audit = db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id, action="update").one()
        assert audit.user_id == manager_id
        assert audit.old_value_json is None
        assert audit.new_value_json == {
            "title": title,
            "description": "x" * 300,
            "assigned_to": next_assignee,
            "status": "completed",
            "priority": "urgent",
            "entity_type": "WorkOrder",
            "entity_id": 42,
        }
    chain(sessions)


@pytest.mark.parametrize(
    ("actor_kind", "payload", "expected_status", "expected_detail"),
    [
        ("outsider", {"status": "completed"}, 403, "Not allowed"),
        ("assignee", {"title": "denied"}, 403, "Assignees can only change status"),
        ("creator", {"assigned_to": "target"}, 403, "Only managers can assign tasks to other users"),
        ("denied_manager", {"assigned_to": "target"}, 403, "Only managers can assign tasks to other users"),
        ("manager", {"assigned_to": 2_000_000_000, "title": "not saved"}, 404, "Assigned user not found"),
    ],
)
def test_pg_task_patch_denials_preserve_task_notifications_and_audit(
    customer_pg_sessions, actor_kind, payload, expected_status, expected_detail,
):
    sessions = customer_pg_sessions
    creator_id = actor(sessions)
    denied_manager_id = actor(
        sessions,
        permissions=["*"],
        access_policy={"MIL": {"deny": ["tasks.manage"]}},
    )
    assignee_id = actor(sessions)
    target_id = actor(sessions)
    task_creator_id = denied_manager_id if actor_kind == "denied_manager" else creator_id
    task_id, _ = task_row(sessions, creator_id=task_creator_id, assigned_to=assignee_id)
    actor_ids = {
        "outsider": actor(sessions),
        "assignee": assignee_id,
        "creator": creator_id,
        "denied_manager": denied_manager_id,
        "manager": actor(sessions, permissions=["tasks.manage"]),
    }
    selected_payload = dict(payload)
    if selected_payload.get("assigned_to") == "target":
        selected_payload["assigned_to"] = target_id
    before = task_snapshot(sessions, task_id)
    with client_for(sessions, actor_ids[actor_kind]) as client:
        response = client.patch(f"/tasks/{task_id}", json=selected_payload)
    assert response.status_code == expected_status, response.text
    assert response.json() == {"detail": expected_detail}
    assert task_snapshot(sessions, task_id) == before


def test_pg_task_patch_preserves_omission_nullable_values_and_completion_time(customer_pg_sessions):
    sessions = customer_pg_sessions
    creator_id = actor(sessions, permissions=["tasks.manage"])
    assignee_id = actor(sessions)
    completed_at = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)
    task_id, _ = task_row(
        sessions,
        creator_id=creator_id,
        assigned_to=assignee_id,
        status="completed",
        completed_at=completed_at,
    )
    with client_for(sessions, creator_id) as client:
        omitted = client.patch(
            f"/tasks/{task_id}",
            json={"assigned_to": None, "description": None, "entity_type": None, "entity_id": None},
        )
        assert omitted.status_code == 200, omitted.text
        assert omitted.json()["status"] == "completed" and omitted.json()["priority"] == "medium"
        assert omitted.json()["assigned_to"] is None
        assert omitted.json()["completed_at"] == completed_at.isoformat().replace("+00:00", "Z")
        changed = client.patch(f"/tasks/{task_id}", json={"status": "in_progress"})
        assert changed.status_code == 200 and changed.json()["completed_at"] is None
        completed = client.patch(f"/tasks/{task_id}", json={"status": "completed"})
        assert completed.status_code == 200 and completed.json()["completed_at"]
        timestamp = completed.json()["completed_at"]
        repeated = client.patch(f"/tasks/{task_id}", json={"status": "completed"})
        assert repeated.status_code == 200 and repeated.json()["completed_at"] == timestamp
    with sessions() as db:
        saved = db.get(Task, task_id)
        assert saved is not None
        assert (saved.assigned_to, saved.description, saved.entity_type, saved.entity_id) == (None, None, None, None)
        updates = db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id, action="update").order_by(AuditLog.id).all()
        assert len(updates) == 4
        assert updates[0].new_value_json == {
            "assigned_to": None,
            "description": None,
            "entity_type": None,
            "entity_id": None,
        }
        assert task_snapshot(sessions, task_id)[2] == []
        assert updates[1].new_value_json == {"status": "in_progress"}
        assert updates[2].new_value_json == updates[3].new_value_json == {"status": "completed"}
    chain(sessions)


@pytest.mark.parametrize("field", ["title", "status", "priority"])
def test_pg_task_patch_explicit_null_not_null_fields_keep_database_failure_semantics(customer_pg_sessions, field):
    sessions = customer_pg_sessions
    manager_id = actor(sessions, permissions=["tasks.manage"])
    task_id, _ = task_row(sessions, creator_id=manager_id, assigned_to=manager_id)
    before = task_snapshot(sessions, task_id)
    with client_for(sessions, manager_id) as client:
        response = client.patch(f"/tasks/{task_id}", json={field: None})
    assert response.status_code == 500
    assert task_snapshot(sessions, task_id) == before


@pytest.mark.parametrize(
    "failure_point",
    ["after_notification_flush", "audit_finalize", "before_commit_hook"],
)
def test_pg_task_patch_failure_rolls_back_then_retry(customer_pg_sessions, monkeypatch, failure_point):
    sessions = customer_pg_sessions
    manager_id = actor(sessions, permissions=["tasks.manage"])
    previous_assignee = actor(sessions)
    next_assignee = actor(sessions)
    task_id, original_title = task_row(sessions, creator_id=manager_id, assigned_to=previous_assignee)
    before = task_snapshot(sessions, task_id)
    original_log = tasks_service.log_action
    original_add_audits = audit_service.add_audit_log_rows
    reached = []
    notification_flush_witnesses = []

    def fail(*_args, **_kwargs):
        reached.append(failure_point)
        raise RuntimeError(f"injected task PATCH {failure_point}")

    def log_then_fail(db, *args, **kwargs):
        result = original_log(db, *args, **kwargs)
        if failure_point == "after_notification_flush":
            notification_flush_witnesses.append(db.query(Notification).filter_by(
                user_id=next_assignee,
                title=f"Task reassigned to you: {original_title}",
            ).count())
            assert notification_flush_witnesses[-1] == 1
            fail()
        if failure_point == "before_commit_hook":
            event.listen(db, "before_commit", fail)
        return result

    payload = {"assigned_to": next_assignee, "description": "changed before injected failure"}
    with monkeypatch.context() as patch:
        patch.setattr(tasks_service, "log_action", log_then_fail)
        if failure_point == "audit_finalize":
            patch.setattr(audit_service, "add_audit_log_rows", fail)
        with client_for(sessions, manager_id) as client:
            failed = client.patch(f"/tasks/{task_id}", json=payload)
            assert failed.status_code == 500
        assert reached == [failure_point]
        if failure_point == "after_notification_flush":
            assert notification_flush_witnesses == [1]
    assert task_snapshot(sessions, task_id) == before
    with client_for(sessions, manager_id) as client:
        retried = client.patch(f"/tasks/{task_id}", json=payload)
    assert retried.status_code == 200, retried.text
    assert retried.json()["assigned_to"] == next_assignee
    with sessions() as db:
        assert db.query(Notification).filter_by(user_id=next_assignee, title=f"Task reassigned to you: {retried.json()['title']}").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id, action="update").count() == 1
        saved = db.get(Task, task_id)
        assert saved is not None and saved.description == "changed before injected failure"
    chain(sessions)


def test_pg_task_patch_concurrent_disjoint_fields_merge_with_two_audits(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    first_manager = actor(sessions, permissions=["tasks.manage"])
    second_manager = actor(sessions, permissions=["tasks.manage"])
    task_id, original_title = task_row(sessions, creator_id=first_manager, assigned_to=first_manager)
    with sessions() as db:
        initial_task_count = db.query(Task).count()

    barrier = Barrier(2, timeout=8)
    guard = Lock()
    request_sessions = []
    rows_at_boundary = []
    original_apply = tasks_service.apply_user_task_update

    def synchronize_after_validation(db, row, command, **kwargs):
        assert object_session(row) is db
        assert row.title == original_title and row.description == "Original description"
        with guard:
            request_sessions.append(db)
            rows_at_boundary.append(row)
        barrier.wait()
        return original_apply(db, row, command, **kwargs)

    monkeypatch.setattr(tasks_service, "apply_user_task_update", synchronize_after_validation)
    new_title = f"Task PATCH concurrent {uuid4().hex}"
    new_description = f"Concurrent description {uuid4().hex}"

    def patch_task(actor_id, payload):
        with client_for(sessions, actor_id) as client:
            return client.patch(f"/tasks/{task_id}", json=payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        title_future = pool.submit(patch_task, first_manager, {"title": new_title})
        description_future = pool.submit(patch_task, second_manager, {"description": new_description})
        title_response = title_future.result(timeout=25)
        description_response = description_future.result(timeout=25)

    assert title_response.status_code == 200, title_response.text
    assert description_response.status_code == 200, description_response.text
    assert len(request_sessions) == len({id(db) for db in request_sessions}) == 2
    assert len(rows_at_boundary) == 2 and rows_at_boundary[0] is not rows_at_boundary[1]
    with sessions() as db:
        saved = db.get(Task, task_id)
        assert saved is not None
        assert (saved.title, saved.description) == (new_title, new_description)
        assert db.query(Task).count() == initial_task_count
        audits = db.query(AuditLog).filter_by(
            entity_type="Task", entity_id=task_id, action="update"
        ).order_by(AuditLog.id).all()
        assert len(audits) == 2
        assert all(row.old_value_json is None for row in audits)
        assert {row.user_id for row in audits} == {first_manager, second_manager}
        assert all(set(row.new_value_json) in ({"title"}, {"description"}) for row in audits)
        assert {
            (row.user_id, row.new_value_json.get("title"), row.new_value_json.get("description"))
            for row in audits
        } == {
            (first_manager, new_title, None),
            (second_manager, None, new_description),
        }
        assert db.query(Notification).filter(
            Notification.title.in_(
                [
                    f"Task reassigned to you: {original_title}",
                    f"Task reassigned to you: {new_title}",
                ]
            )
        ).count() == 0
    chain(sessions)


def test_pg_task_patch_repeat_has_no_idempotency_or_repeat_assignment_notice(customer_pg_sessions):
    sessions = customer_pg_sessions
    manager_id = actor(sessions, permissions=["tasks.manage"])
    previous_assignee = actor(sessions)
    next_assignee = actor(sessions)
    task_id, _ = task_row(sessions, creator_id=manager_id, assigned_to=previous_assignee)
    with client_for(sessions, manager_id) as client:
        first = client.patch(f"/tasks/{task_id}", json={"assigned_to": next_assignee})
        second = client.patch(f"/tasks/{task_id}", json={"assigned_to": next_assignee})
    assert first.status_code == second.status_code == 200
    with sessions() as db:
        notices = db.query(Notification).filter_by(
            user_id=next_assignee,
            title=f"Task reassigned to you: {first.json()['title']}",
        ).all()
        audits = db.query(AuditLog).filter_by(entity_type="Task", entity_id=task_id, action="update").all()
        assert len(notices) == 1
        assert len(audits) == 2
        assert all(row.new_value_json == {"assigned_to": next_assignee} for row in audits)
    chain(sessions)
