"""A task target must survive validation until the task transaction commits."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import os

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks
from app.db.base import Base
from app.libs.dto.work_management.tasks import TaskIn, TaskUpdate
from app.schemas import AuditLog, Notification, SalesOrder, Task, User


@pytest.fixture
def pg_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires isolated PostgreSQL on loopback")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost", "::1"} and not url.query
    schema = f"api02_{uuid4().hex}"
    engine = create_engine(url, connect_args={
        "options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"
    }, pool_size=3, max_overflow=0)
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_reference_delete_waits_for_task_commit(pg_sessions, monkeypatch):
    with pg_sessions() as db:
        actor = User(name="Task race actor", email=f"api02-{uuid4().hex}@example.invalid",
                     password_hash="unused", extra_permissions=["tasks.manage"])
        order = SalesOrder(order_no=f"SO-API02-{uuid4().hex[:10]}")
        db.add_all((actor, order))
        db.commit()
        actor_id, order_id = actor.id, order.id

    entered, release, delete_started, delete_done = Event(), Event(), Event(), Event()
    original_log_action = tasks.log_action

    def pause_at_audit(*args, **kwargs):
        entered.set()
        assert release.wait(5), "Task writer was not released"
        return original_log_action(*args, **kwargs)

    monkeypatch.setattr(tasks, "log_action", pause_at_audit)

    def create():
        with pg_sessions() as db:
            actor = db.get(User, actor_id)
            return tasks.create_task(TaskIn(title="Locked reference", entity_type="SalesOrder", entity_id=order_id), db, actor).id

    def delete():
        with pg_sessions() as db:
            delete_started.set()
            db.query(SalesOrder).filter(SalesOrder.id == order_id).delete(synchronize_session=False)
            db.commit()
            delete_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(create)
        assert entered.wait(5), "Task writer did not reach the audit"
        deleter = pool.submit(delete)
        try:
            assert delete_started.wait(5)
            assert not delete_done.wait(0.2), "Reference row was deleted before the task committed"
        finally:
            release.set()
        assert writer.result(timeout=5) > 0
        deleter.result(timeout=5)
        assert delete_done.is_set()


@pytest.mark.parametrize("reassign", [False, True], ids=["status", "reassignment"])
def test_patch_after_concurrent_delete_matches_missing_task(pg_sessions, monkeypatch, reassign):
    with pg_sessions() as db:
        actor = User(name="Task race actor", email=f"api02-{uuid4().hex}@example.invalid",
                     password_hash="unused", extra_permissions=["tasks.manage"])
        recipient = User(name="Task race recipient", email=f"api02-{uuid4().hex}@example.invalid",
                         password_hash="unused")
        db.add_all((actor, recipient))
        db.flush()
        task = Task(title="Deleted during patch", created_by=actor.id, assigned_to=actor.id)
        db.add(task)
        db.commit()
        actor_id, recipient_id, tid = actor.id, recipient.id, task.id

    payload = TaskUpdate(assigned_to=recipient_id) if reassign else TaskUpdate(status="completed")
    read, deleted = Event(), Event()
    original_validate = tasks.validate_task_reference_update

    def pause_after_read(*args, **kwargs):
        reference = original_validate(*args, **kwargs)
        read.set()
        assert deleted.wait(5), "Concurrent deletion did not finish"
        return reference

    monkeypatch.setattr(tasks, "validate_task_reference_update", pause_after_read)

    def patch():
        with pg_sessions() as db:
            try:
                return tasks.update_task(tid, payload, db, db.get(User, actor_id))
            except HTTPException:
                assert db.is_active, "PATCH must roll back its failed flush"
                assert db.query(Notification).count() == 0
                raise

    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(patch)
        try:
            assert read.wait(5), "PATCH did not load the task"
            with pg_sessions() as db:
                tasks.delete_task(tid, db, db.get(User, actor_id))
        finally:
            deleted.set()
        with pytest.raises(HTTPException) as raced:
            writer.result(timeout=5)

    with pg_sessions() as db:
        with pytest.raises(HTTPException) as missing:
            tasks.update_task(tid, payload, db, db.get(User, actor_id))
        assert (raced.value.status_code, raced.value.detail) == (
            missing.value.status_code, missing.value.detail
        ) == (404, "Task not found")
        assert db.get(Task, tid) is None
        assert db.query(Notification).count() == 0
        audits = db.query(AuditLog).filter_by(entity_type="Task", entity_id=tid).all()
        assert [entry.action for entry in audits] == ["delete"]
