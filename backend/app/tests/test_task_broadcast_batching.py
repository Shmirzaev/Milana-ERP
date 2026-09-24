import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import tasks
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Notification, SalesOrder, Task, User
from app.schemas.tasks import TaskIn


@pytest.fixture(params=["sqlite", "postgres"])
def broadcast_sessions(request):
    if request.param == "sqlite":
        yield SessionLocal
        return
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost", "::1"} and not url.query
    schema = f"broadcast_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _actor(db):
    actor = User(name="Broadcast manager", email=f"broadcast-{uuid4().hex}@example.invalid",
                 password_hash="unused", extra_permissions=["tasks.manage"], is_active=True)
    db.add(actor)
    db.flush()
    return actor


@pytest.mark.parametrize("recipients", [1, 50])
def test_broadcast_batches_flushes_preserving_tasks_notifications_and_audit(
    broadcast_sessions,
    monkeypatch,
    recipients,
):
    marker = uuid4().hex
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "250")
    with broadcast_sessions() as db:
        admin = _actor(db)
        db.query(User).update({"is_active": False}, synchronize_session=False)
        users = [User(name=f"Recipient{i}", email=f"{marker}-{i}@example.com",
                      password_hash="test-only", is_active=True) for i in range(recipients)]
        sales_order = SalesOrder(order_no=f"BROADCAST-{marker}")
        db.add_all([*users, sales_order])
        db.commit()
        user_ids = [user.id for user in users]
        title = f"Broadcast {marker}"
        flushes, inserts, selects, recipient_selects = [], [], [], []

        def before_flush(*_):
            flushes.append(1)

        def before_execute(_conn, _cursor, statement, *_):
            normalized = " ".join(statement.lower().split())
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)
            if "from users" in normalized and "users.is_active" in normalized:
                recipient_selects.append(normalized)
            if statement.lstrip().upper().startswith("INSERT INTO TASKS") or statement.lstrip().upper().startswith("INSERT INTO NOTIFICATIONS"):
                inserts.append(statement)

        event.listen(db, "before_flush", before_flush)
        event.listen(db.bind, "before_cursor_execute", before_execute)
        try:
            first = tasks.create_task(TaskIn(title=title, assigned_to=-1,
                description="x" * 300, entity_type="salesorder", entity_id=sales_order.id), db, admin)
        finally:
            event.remove(db, "before_flush", before_flush)
            event.remove(db.bind, "before_cursor_execute", before_execute)

        rows = db.query(Task).filter(Task.title == title).order_by(Task.id).all()
        notices = db.query(Notification).filter(Notification.title == f"New task: {title}").all()
        assert [row.assigned_to for row in rows] == user_ids
        assert {row.user_id for row in notices} == set(user_ids)
        assert all(
            row.message == "x" * 280 and row.link == f"/sales-orders/{sales_order.id}"
            for row in notices
        )
        assert first.id == rows[0].id
        audit = db.query(AuditLog).filter(AuditLog.entity_type == "Task", AuditLog.entity_id == first.id).one()
        assert audit.new_value_json["created_count"] == recipients
        assert len(flushes) == 2  # One task/notification flush, one audit flush.
        expected_selects = 6 if db.bind.dialect.name == "postgresql" else 4
        assert len(selects) == expected_selects
        assert len(recipient_selects) == 1
        recipient_projection = recipient_selects[0].split(" from users", 1)[0]
        assert " limit " in recipient_selects[0]
        assert "users.password_hash" not in recipient_projection
        assert "users.email" not in recipient_projection
        assert "users.name" not in recipient_projection
        assert "users.last_login_at" not in recipient_projection
        assert "users.last_seen_at" not in recipient_projection
        assert "users.tokens_valid_from" not in recipient_projection
        assert "users.factory_code" in recipient_projection
        assert "users.extra_permissions" in recipient_projection
        assert "users.access_policy" in recipient_projection
        assert "roles_1.permissions" in recipient_projection
        assert "departments_1.code" in recipient_projection
        if db.bind.dialect.name == "postgresql":
            assert len(inserts) == 2


def test_oversized_broadcast_rejects_after_bounded_read_before_policy_or_writes(
    broadcast_sessions,
    monkeypatch,
):
    marker = uuid4().hex
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "250")
    with broadcast_sessions() as db:
        admin = _actor(db)
        db.query(User).update({"is_active": False}, synchronize_session=False)
        users = [
            User(
                name=f"Recipient{i}",
                email=f"{marker}-{i}@example.com",
                password_hash="test-only",
                is_active=True,
            )
            for i in range(401)
        ]
        sales_order = SalesOrder(order_no=f"BROADCAST-{marker}")
        db.add_all([*users, sales_order])
        db.commit()
        title = f"Oversized broadcast {marker}"
        flushes: list[int] = []
        selects: list[str] = []
        recipient_selects: list[tuple[str, object]] = []

        def before_flush(*_args):
            flushes.append(1)

        def before_execute(_connection, _cursor, statement, parameters, *_args):
            normalized = " ".join(statement.lower().split())
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(normalized)
            if "from users" in normalized and "users.is_active" in normalized:
                recipient_selects.append((normalized, parameters))

        def fail_recipient_policy(*_args, **_kwargs):
            raise AssertionError("oversized broadcast must reject before recipient policy checks")

        def fail_audit(*_args, **_kwargs):
            raise AssertionError("oversized broadcast must reject before audit")

        monkeypatch.setattr(tasks, "_require_assignee_reference_access", fail_recipient_policy)
        monkeypatch.setattr(tasks, "log_action", fail_audit)
        event.listen(db, "before_flush", before_flush)
        event.listen(db.bind, "before_cursor_execute", before_execute)
        try:
            with pytest.raises(HTTPException) as exc_info:
                tasks.create_task(
                    TaskIn(
                        title=title,
                        assigned_to=-1,
                        entity_type="salesorder",
                        entity_id=sales_order.id,
                    ),
                    db,
                    admin,
                )
        finally:
            event.remove(db, "before_flush", before_flush)
            event.remove(db.bind, "before_cursor_execute", before_execute)

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == (
            "Recipient count exceeds ERP_MCP_MAX_BULK_RECIPIENTS=250"
        )
        assert len(recipient_selects) == 1
        statement, parameters = recipient_selects[0]
        assert " limit " in statement
        parameter_values = parameters.values() if isinstance(parameters, dict) else parameters
        assert 251 in parameter_values
        assert flushes == []
        assert len(selects) == 2
        assert selects[-1] == statement
        assert not db.new
        assert not db.dirty
        assert db.query(Task).filter(Task.title == title).count() == 0
        assert db.query(Notification).filter(Notification.title == f"New task: {title}").count() == 0
        assert db.query(AuditLog).filter(
            AuditLog.entity_type == "Task",
            AuditLog.new_value_json["title"].as_string() == title,
        ).count() == 0


def test_failed_broadcast_can_roll_back_tasks_and_notifications(broadcast_sessions, monkeypatch):
    marker = uuid4().hex
    with broadcast_sessions() as db:
        admin = _actor(db)
        db.commit()

        def fail_audit(*args, **kwargs):
            raise RuntimeError("Synthetic audit failure")

        monkeypatch.setattr(tasks, "log_action", fail_audit)
        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
            tasks.create_task(TaskIn(title=marker, assigned_to=-1), db, admin)
        db.rollback()
        assert db.query(Task).filter_by(title=marker).count() == 0
        assert db.query(Notification).filter_by(title=f"New task: {marker}").count() == 0
