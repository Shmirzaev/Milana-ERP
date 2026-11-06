"""Existing Eco Band writes and Work reads on SQLite and disposable PostgreSQL."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import notifications, tasks
from app.models.sewing_band_setup_service import BAND_PERMISSIONS, configure_eco_bands
from app.schemas import AuditLog, Department, Notification, Role, SewingFlow, Task, User
from app.tests.test_task_broadcast_batching import broadcast_sessions as broadcast_sessions


def _user(db, *, permissions=()):
    user = User(name="Boundary actor", email=f"boundary-{uuid4().hex}@example.invalid",
                password_hash="fixture", extra_permissions=list(permissions), is_active=True)
    db.add(user)
    db.flush()
    return user


def test_eco_band_provisioning_keeps_one_outer_transaction_and_retry(broadcast_sessions):
    with broadcast_sessions() as db:
        actor = _user(db)
        if db.query(Department).filter_by(code="ECO").first() is None:
            db.add(Department(name=f"ECO {uuid4().hex}", code="ECO"))
        for n in range(1, 12):
            code = f"ECO-BAND-{n:02}"
            if db.query(SewingFlow).filter_by(factory_code="ECO", code=code).first() is None:
                db.add(SewingFlow(factory_code="ECO", code=code, name=f"Band {n}"))
        db.commit()
        baseline = db.query(AuditLog).count()
        expected_retire = [flow.code for flow in db.query(SewingFlow).filter_by(factory_code="ECO", is_active=True)
                           .order_by(SewingFlow.id) if flow.code not in {f"ECO-BAND-{n:02}" for n in range(1, 11)}]

        preview = configure_eco_bands(db, actor)
        assert preview["retire"] == expected_retire
        assert len(preview["create"]) == 10
        assert db.query(User).filter(User.sewing_band_id.isnot(None)).count() == 0
        assert db.query(Role).filter(Role.name == "Eco Band").count() == 0

        result = configure_eco_bands(db, actor, "Fixture!123456", apply=True)
        assert result == preview
        role = db.query(Role).filter(Role.name == "Eco Band").one()
        assert role.permissions == BAND_PERMISSIONS
        assert db.query(User).filter(User.sewing_band_id.isnot(None)).count() == 10
        assert db.query(SewingFlow).filter_by(code="ECO-BAND-11", factory_code="ECO").one().is_active is False
        # PostgreSQL queues audit rows until the caller commits; SQLite inserts now.
        before_commit = baseline if db.bind.dialect.name == "postgresql" else baseline + 11 + len(expected_retire)
        assert db.query(AuditLog).count() == before_commit
        assert db.in_transaction()
        db.rollback()
        assert db.query(Role).filter(Role.name == "Eco Band").count() == 0
        assert db.query(User).filter(User.sewing_band_id.isnot(None)).count() == 0
        assert db.query(SewingFlow).filter_by(code="ECO-BAND-11", factory_code="ECO").one().is_active is True

        db.expire_all()
        configure_eco_bands(db, actor, "Fixture!123456", apply=True)
        db.commit()
        again = configure_eco_bands(db, actor, "Different!123456", apply=True)
        assert again["create"] == [] and len(again["keep"]) == 10
        assert db.query(AuditLog).count() == baseline + 11 + len(expected_retire)


def test_task_reads_keep_scope_order_count_and_refusals(broadcast_sessions):
    with broadcast_sessions() as db:
        manager = _user(db, permissions=("tasks.manage",))
        assignee = _user(db)
        outsider = _user(db)
        rows = [
            Task(title="First", assigned_to=assignee.id, created_by=manager.id, status="pending"),
            Task(title="Second", assigned_to=assignee.id, created_by=manager.id, status="completed"),
            Task(title="Third", assigned_to=manager.id, created_by=outsider.id, status="in_progress"),
        ]
        db.add_all(rows)
        db.commit()

        assert [row.id for row in tasks.list_tasks(db, assignee)] == [rows[1].id, rows[0].id]
        assert [row.id for row in tasks.list_tasks(db, manager, scope="created")] == [rows[1].id, rows[0].id]
        assert [row.id for row in tasks.list_tasks(db, manager, scope="all")] == [rows[2].id, rows[1].id, rows[0].id]
        from app.libs.enums.work_management import TaskStatus
        assert [row.id for row in tasks.list_tasks(db, manager, scope="all", status=TaskStatus.PENDING)] == [rows[0].id]
        assert tasks.open_task_count(db, assignee) == {"count": 1}
        assert tasks.get_task(rows[0].id, db, assignee).id == rows[0].id
        with pytest.raises(HTTPException) as denied:
            tasks.list_tasks(db, outsider, scope="all")
        assert (denied.value.status_code, denied.value.detail) == (403, "Only managers can list all tasks")
        with pytest.raises(HTTPException) as denied:
            tasks.get_task(rows[0].id, db, outsider)
        assert (denied.value.status_code, denied.value.detail) == (403, "Not allowed")
        with pytest.raises(HTTPException) as missing:
            tasks.get_task(2_000_000_000, db, manager)
        assert (missing.value.status_code, missing.value.detail) == (404, "Task not found")


def test_notification_reads_keep_bounds_scope_and_summary(broadcast_sessions):
    with broadcast_sessions() as db:
        actor = _user(db)
        other = _user(db)
        rows = [
            Notification(user_id=actor.id, title="Old", is_read=False),
            Notification(user_id=actor.id, title="Read", is_read=True),
            Notification(user_id=actor.id, title="New", is_read=False),
            Notification(user_id=other.id, title="Private", is_read=False),
        ]
        db.add_all(rows)
        db.commit()

        assert [row.id for row in notifications.list_my_notifications(db, actor)] == [rows[2].id, rows[1].id, rows[0].id]
        assert [row.id for row in notifications.list_my_notifications(db, actor, only_unread=True, limit=1)] == [rows[2].id]
        assert notifications.list_my_notifications(db, actor, limit=0) == []
        assert notifications.unread_count(db, actor) == {"count": 2}
        assert notifications.unread_count(db, other) == {"count": 1}
        summary = notifications.notification_summary(db, actor, limit=1)
        assert summary["count"] == 2
        assert [row["id"] for row in summary["rows"]] == [rows[2].id]
        assert db.query(AuditLog).count() == 0
