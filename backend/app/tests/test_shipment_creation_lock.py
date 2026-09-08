"""Shipment-create replay/existence checks must run after a refreshed order lock."""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app.api.routes import shipments
from app.db.session import SessionLocal
from app.models import SalesOrder, Shipment, User
from app.schemas.sales import ShipmentIn


def ready_order():
    with SessionLocal() as db:
        order = SalesOrder(order_no=f"SO-CREATE-LOCK-{uuid4().hex[:8]}", status="ready", order_type="client_order")
        db.add(order); db.commit()
        return order.id


def test_creation_locks_order_before_replay_and_duplicate_check(monkeypatch):
    oid = ready_order()
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="fgs@example.com").one()
        payload = ShipmentIn(sales_order_id=oid)
        events = []

        def observe(orm):
            statement = orm.statement
            if getattr(statement, "_for_update_arg", None) is not None:
                sql = str(statement.compile(dialect=postgresql.dialect()))
                if "FOR UPDATE OF sales_orders" in sql:
                    assert orm.load_options._populate_existing
                    events.append("locked-order")

        replay_original = shipments.replay_idempotent_response
        exists_original = shipments._shipment_exists_for_sales_order

        def replay(*args, **kwargs):
            assert events[-1] == "locked-order", events
            events.append("replay")
            return replay_original(*args, **kwargs)

        def exists(*args, **kwargs):
            assert events[-1] == "replay", events
            events.append("exists")
            return exists_original(*args, **kwargs)

        event.listen(db, "do_orm_execute", observe)
        monkeypatch.setattr(shipments, "replay_idempotent_response", replay)
        monkeypatch.setattr(shipments, "_shipment_exists_for_sales_order", exists)
        key = str(uuid4())
        first = shipments.create_shipment(payload, db, user, key)
        assert events == ["locked-order", "replay", "exists"]
        events.clear()
        assert shipments.create_shipment(payload, db, user, key) == jsonable_encoder(first)
        assert events == ["locked-order", "replay"]
        events.clear()
        with pytest.raises(HTTPException) as conflict:
            shipments.create_shipment(payload, db, user, str(uuid4()))
        assert conflict.value.status_code == 409
        assert events == ["locked-order", "replay", "exists"]
        assert db.query(Shipment).filter_by(sales_order_id=oid).count() == 1


def test_creation_refreshes_cached_order_after_concurrent_status_change():
    oid = ready_order()
    with SessionLocal() as db:
        cached = db.get(SalesOrder, oid)
        assert cached.status == "ready"
        user = db.query(User).filter_by(email="fgs@example.com").one()
        with SessionLocal() as other:
            other.get(SalesOrder, oid).status = "cancelled"
            other.commit()
        assert cached.status == "ready"
        with pytest.raises(HTTPException) as rejected:
            shipments.create_shipment(ShipmentIn(sales_order_id=oid), db, user, None)
        assert rejected.value.status_code == 409
        assert cached.status == "cancelled"
        assert db.query(Shipment).filter_by(sales_order_id=oid).count() == 0
