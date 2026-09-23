import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import notifications as notification_routes
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import AuditLog, Department, Notification, User


@pytest.fixture(params=["sqlite", "postgres"])
def notification_sessions(request):
    if request.param == "sqlite":
        yield SessionLocal
        return
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"}
    assert not url.query
    schema = f"notification_fanout_{uuid4().hex}"
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


def _fanout_case(sessions, recipients: int):
    marker = uuid4().hex[:10]
    with sessions() as db:
        department = Department(name=f"Notification {marker}", code=f"N{marker[:7]}")
        actor = User(
            name="Notification manager",
            email=f"notification-manager-{marker}@example.invalid",
            password_hash="unused",
            extra_permissions=["management.view"],
            is_active=True,
        )
        users = [
            User(
                name=f"Recipient {index:03d}",
                email=f"notification-recipient-{marker}-{index}@example.invalid",
                password_hash="unused",
                department=department,
                is_active=True,
            )
            for index in range(recipients)
        ]
        db.add_all([department, actor, *users])
        db.commit()
        return {
            "department_code": department.code,
            "actor_id": int(actor.id),
            "user_ids": [int(user.id) for user in users],
            "title": f"Fan-out {marker}",
        }


@pytest.mark.parametrize("recipients", [1, 50, 250])
def test_notification_fanout_batches_flushes_and_preserves_response(
    notification_sessions,
    monkeypatch,
    recipients,
):
    case = _fanout_case(notification_sessions, recipients)
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "250")
    with notification_sessions() as db:
        actor = db.get(User, case["actor_id"])
        flushes: list[int] = []
        notification_inserts: list[str] = []
        recipient_selects: list[str] = []
        user_selects: list[str] = []

        def capture_flush(*_args):
            flushes.append(1)

        def capture_insert(_connection, _cursor, statement, *_args):
            normalized = " ".join(statement.lower().split())
            if statement.lstrip().upper().startswith("INSERT INTO NOTIFICATIONS"):
                notification_inserts.append(statement)
            if (
                "from departments" in normalized
                and "lower(departments.code)" in normalized
            ) or (
                "from users" in normalized
                and "users.department_id" in normalized
                and "users.is_active" in normalized
            ):
                recipient_selects.append(statement)
            if "from users" in normalized and "users.department_id" in normalized:
                user_selects.append(normalized)

        event.listen(db, "before_flush", capture_flush)
        event.listen(db.bind, "before_cursor_execute", capture_insert)
        try:
            response = notification_routes.send_notification(
                notification_routes.NotificationSendIn(
                    target_type="department",
                    department=case["department_code"].lower(),
                    title=f"  {case['title']}  ",
                    message="  Bounded delivery  ",
                    link="/tasks",
                    entity_type="Task",
                    entity_id=123,
                ),
                db,
                actor,
            )
        finally:
            event.remove(db, "before_flush", capture_flush)
            event.remove(db.bind, "before_cursor_execute", capture_insert)

        rows = db.query(Notification).filter(Notification.title == case["title"]).order_by(Notification.id).all()
        audit = db.query(AuditLog).filter(
            AuditLog.action == "mcp_send_notification",
            AuditLog.new_value_json["title"].as_string() == case["title"],
        ).one()

        assert len(flushes) == 2
        assert len(recipient_selects) == 2
        assert len(user_selects) == 1
        user_projection = user_selects[0].split(" from users", 1)[0]
        assert "users.password_hash" not in user_projection
        assert "users.extra_permissions" not in user_projection
        assert "users.access_policy" not in user_projection
        assert "join roles" not in user_selects[0]
        assert "join departments" not in user_selects[0]
        if db.bind.dialect.name == "postgresql":
            assert len(notification_inserts) == 1
        assert [row.user_id for row in rows] == case["user_ids"]
        assert all(row.message == "Bounded delivery" and row.link == "/tasks" for row in rows)
        assert response["message"] == "notification_sent"
        assert response["created_count"] == recipients
        assert response["notification_ids"] == [int(row.id) for row in rows]
        assert [row["user_id"] for row in response["recipients"]] == case["user_ids"]
        assert response["title"] == case["title"]
        assert response["link"] == "/tasks"
        assert response["linked_entity"] == {"entity_type": "Task", "entity_id": 123}
        assert response["requested_by"] == {"user_id": case["actor_id"], "name": actor.name}
        assert response["timestamp"]
        assert audit.new_value_json["recipient_user_ids"] == case["user_ids"]
        assert audit.new_value_json["created_count"] == recipients


def test_notification_fanout_audit_failure_rolls_back_delivery(
    notification_sessions,
    monkeypatch,
):
    case = _fanout_case(notification_sessions, 3)
    monkeypatch.setenv("ERP_MCP_MAX_BULK_RECIPIENTS", "250")

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("Synthetic notification audit failure")

    monkeypatch.setattr(notification_routes, "log_action", fail_audit)
    with notification_sessions() as db:
        actor = db.get(User, case["actor_id"])
        with pytest.raises(RuntimeError, match="Synthetic notification audit failure"):
            notification_routes.send_notification(
                notification_routes.NotificationSendIn(
                    target_type="department",
                    department=case["department_code"],
                    title=case["title"],
                ),
                db,
                actor,
            )
        db.rollback()
        assert db.query(Notification).filter(Notification.title == case["title"]).count() == 0
        assert db.query(AuditLog).filter(
            AuditLog.action == "mcp_send_notification",
            AuditLog.new_value_json["title"].as_string() == case["title"],
        ).count() == 0


def test_notification_send_requires_management_permission(client):
    login = client.post(
        "/api/auth/token",
        data={"username": "sales@example.com", "password": "demo12345"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    marker = uuid4().hex[:10]
    response = client.post(
        "/api/notifications/send",
        headers=headers,
        json={
            "target_type": "user_id",
            "user_id": 1,
            "title": f"Forbidden fan-out {marker}",
        },
    )
    assert response.status_code == 403, response.text
    with SessionLocal() as db:
        assert db.query(Notification).filter(Notification.title == f"Forbidden fan-out {marker}").count() == 0
        assert db.query(AuditLog).filter(
            AuditLog.action == "mcp_send_notification",
            AuditLog.new_value_json["title"].as_string() == f"Forbidden fan-out {marker}",
        ).count() == 0
