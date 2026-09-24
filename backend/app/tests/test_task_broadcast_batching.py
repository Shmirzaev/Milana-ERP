import os
from uuid import uuid4

import pytest
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
def test_broadcast_batches_flushes_preserving_tasks_notifications_and_audit(broadcast_sessions, recipients):
    marker = uuid4().hex
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
        flushes, inserts, selects = [], [], []

        def before_flush(*_):
            flushes.append(1)

        def before_execute(_conn, _cursor, statement, *_):
            normalized = statement.lstrip().upper()
            if normalized.startswith("SELECT"):
                selects.append(statement)
            if normalized.startswith("INSERT INTO TASKS") or normalized.startswith("INSERT INTO NOTIFICATIONS"):
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
        assert len(selects) <= 8  # Reference authorization stays constant at 1/50 recipients.
        if db.bind.dialect.name == "postgresql":
            assert len(inserts) == 2


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
