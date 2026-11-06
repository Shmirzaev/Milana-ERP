"""Sales confirmation persists through the schema API and the caller's transaction.

Run independently with ``pytest --noconftest``. The in-memory SQLite database
owns its schema and does not require the shared test database or API fixtures.
"""

import inspect

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.deps import get_current_user
from app.db.base import Base
from app.db.session import get_db
from app.libs.enums.sales import SalesOrderStatus
from app.models.audit_service import log_action as real_log_action
from app.models.sales import orders_service
from app.models.workflow_service import notify_department as real_notify_department
from app.schemas import AuditLog, Department, Notification, SalesOrder, User
from app.schemas.sales import sales_order_persistence


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False, expire_on_commit=False) as session:
        yield session
        session.rollback()
    engine.dispose()


def _actor(db):
    actor = User(name="Sales confirmer", email="confirm@example.test", password_hash="unused")
    db.add(actor)
    db.commit()
    return actor


def _order(db, status="draft"):
    order = SalesOrder(order_no=f"CONFIRM-{status}", status=status, total_amount=12)
    db.add(order)
    db.commit()
    return order


def _record_effects(db, monkeypatch):
    """Stub shared participants while retaining real ORM rows for service tests."""
    sequence = []

    def notify(supplied, **kwargs):
        sequence.append(("notification", supplied, kwargs))
        supplied.add(Notification(
            user_id=kwargs["exclude_user_id"],
            title=kwargs["title"],
            message=kwargs["message"],
            link=kwargs["link"],
        ))

    def audit(supplied, actor, action, entity_type, entity_id):
        sequence.append(("audit", supplied, actor, action, entity_type, entity_id))
        supplied.add(AuditLog(
            user_id=actor.id, action=action, entity_type=entity_type, entity_id=entity_id,
        ))

    monkeypatch.setattr(orders_service, "notify_department", notify)
    monkeypatch.setattr(orders_service, "log_action", audit)
    return sequence


def test_confirmation_uses_typed_schema_writer_and_commits_order_and_effects(db, monkeypatch):
    actor = _actor(db)
    order = _order(db)
    sequence = _record_effects(db, monkeypatch)
    writer_calls = []
    original_writer = sales_order_persistence.set_sales_order_status

    def observe_writer(supplied, row, status):
        writer_calls.append((supplied, row, status))
        return original_writer(supplied, row, status)

    monkeypatch.setattr(orders_service, "set_sales_order_status", observe_writer)
    mapped_writes = []

    def observe_status_set(target, value, oldvalue, initiator):
        mapped_writes.append({frame.function for frame in inspect.stack()})

    event.listen(SalesOrder.status, "set", observe_status_set)
    try:
        result = orders_service.confirm_sales_order(order.id, db, actor)
    finally:
        event.remove(SalesOrder.status, "set", observe_status_set)

    assert result["status"] == SalesOrderStatus.CONFIRMED.value
    assert writer_calls == [(db, order, SalesOrderStatus.CONFIRMED)]
    assert mapped_writes and all("set_sales_order_status" in stack for stack in mapped_writes)
    assert [entry[0] for entry in sequence] == ["notification", "audit"]
    assert all(entry[1] is db for entry in sequence)
    assert sequence[0][2] == {
        "department_code": "PLN",
        "title": f"Sales order {order.order_no} sent to planning",
        "message": "Planning can create the production order now.",
        "link": f"/planning?so_id={order.id}",
        "exclude_user_id": actor.id,
    }
    assert sequence[1][2:] == (actor, "confirm", "SalesOrder", order.id)
    assert db.query(SalesOrder).filter_by(id=order.id).one().status == "confirmed"
    assert db.query(Notification).count() == 1
    assert db.query(AuditLog).filter_by(entity_id=order.id, action="confirm").count() == 1


def test_confirmation_uses_real_planning_notification_and_audit_writers(db, monkeypatch):
    planning = Department(name="Planning", code="PLN")
    db.add(planning)
    db.flush()
    actor = User(
        name="Planning actor", email="planning-actor@example.test", password_hash="unused",
        department_id=planning.id,
    )
    recipient = User(
        name="Planning recipient", email="planning-recipient@example.test", password_hash="unused",
        department_id=planning.id,
    )
    db.add_all([actor, recipient])
    db.commit()
    order = _order(db, "draft")
    calls = []

    def observe_notify(*args, **kwargs):
        calls.append("notification")
        return real_notify_department(*args, **kwargs)

    def observe_audit(*args, **kwargs):
        calls.append("audit")
        return real_log_action(*args, **kwargs)

    monkeypatch.setattr(orders_service, "notify_department", observe_notify)
    monkeypatch.setattr(orders_service, "log_action", observe_audit)
    orders_service.confirm_sales_order(order.id, db, actor)

    assert calls == ["notification", "audit"]
    db.expire_all()
    saved_order = db.get(SalesOrder, order.id)
    assert saved_order.status == SalesOrderStatus.CONFIRMED.value
    notifications = db.query(Notification).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == recipient.id
    assert notifications[0].user_id != actor.id
    assert notifications[0].title == f"Sales order {order.order_no} sent to planning"
    assert notifications[0].message == "Planning can create the production order now."
    assert notifications[0].link == f"/planning?so_id={order.id}"
    audit = db.query(AuditLog).filter_by(entity_type="SalesOrder", entity_id=order.id).one()
    assert audit.user_id == actor.id
    assert audit.action == "confirm"


def test_confirmation_route_denies_user_without_sales_permission(db, monkeypatch):
    actor = _actor(db)
    order = _order(db, "draft")
    app = FastAPI()

    def supplied_db():
        yield db

    app.dependency_overrides[get_db] = supplied_db
    app.dependency_overrides[get_current_user] = lambda: actor
    from app.api.routes.sales import router

    app.include_router(router, prefix="/api")
    monkeypatch.setattr(
        orders_service, "confirm_sales_order",
        lambda *args, **kwargs: pytest.fail("unauthorized request reached Sales confirmation"),
    )
    with TestClient(app) as client:
        response = client.post(f"/api/sales-orders/{order.id}/confirm")
    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(SalesOrder, order.id).status == "draft"
    assert db.query(Notification).count() == db.query(AuditLog).count() == 0


@pytest.mark.parametrize("status", [item.value for item in SalesOrderStatus if item is not SalesOrderStatus.DRAFT])
def test_non_draft_confirmation_refuses_without_effects(db, monkeypatch, status):
    actor = _actor(db)
    order = _order(db, status)

    def forbidden(*args, **kwargs):
        pytest.fail("confirmation side effect or persistence ran for a non-draft order")

    monkeypatch.setattr(orders_service, "set_sales_order_status", forbidden)
    monkeypatch.setattr(orders_service, "notify_department", forbidden)
    monkeypatch.setattr(orders_service, "log_action", forbidden)
    with pytest.raises(HTTPException) as error:
        orders_service.confirm_sales_order(order.id, db, actor)
    assert (error.value.status_code, error.value.detail) == (400, f"Cannot confirm order in status '{status}'")
    assert db.query(SalesOrder).filter_by(id=order.id).one().status == status
    assert db.query(Notification).count() == db.query(AuditLog).count() == 0


def test_missing_order_returns_404_before_writer_or_effects(db, monkeypatch):
    actor = _actor(db)

    def forbidden(*args, **kwargs):
        pytest.fail("missing order reached persistence or side effects")

    monkeypatch.setattr(orders_service, "set_sales_order_status", forbidden)
    monkeypatch.setattr(orders_service, "notify_department", forbidden)
    monkeypatch.setattr(orders_service, "log_action", forbidden)
    with pytest.raises(HTTPException) as error:
        orders_service.confirm_sales_order(987654, db, actor)
    assert (error.value.status_code, error.value.detail) == (404, "Sales order not found")


def test_audit_failure_rolls_back_status_and_preceding_notification(db, monkeypatch):
    actor = _actor(db)
    order = _order(db)
    sequence = []

    def notify(supplied, **kwargs):
        sequence.append("notification")
        supplied.add(Notification(
            user_id=actor.id, title=kwargs["title"], message=kwargs["message"], link=kwargs["link"],
        ))

    def fail_audit(*args, **kwargs):
        sequence.append("audit")
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(orders_service, "notify_department", notify)
    monkeypatch.setattr(orders_service, "log_action", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        orders_service.confirm_sales_order(order.id, db, actor)
    assert sequence == ["notification", "audit"]
    db.rollback()
    assert db.query(SalesOrder).filter_by(id=order.id).one().status == "draft"
    assert db.query(Notification).count() == db.query(AuditLog).count() == 0


def test_schema_writer_failure_prevents_notification_audit_and_status_change(db, monkeypatch):
    actor = _actor(db)
    order = _order(db)

    def fail_writer(*args, **kwargs):
        raise RuntimeError("schema writer unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("side effect ran after schema writer failure")

    monkeypatch.setattr(orders_service, "set_sales_order_status", fail_writer)
    monkeypatch.setattr(orders_service, "notify_department", forbidden)
    monkeypatch.setattr(orders_service, "log_action", forbidden)
    with pytest.raises(RuntimeError, match="schema writer unavailable"):
        orders_service.confirm_sales_order(order.id, db, actor)
    db.rollback()
    assert db.query(SalesOrder).filter_by(id=order.id).one().status == "draft"
    assert db.query(Notification).count() == db.query(AuditLog).count() == 0
