"""Shipment-create replay/existence checks must run after a refreshed order lock."""
from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event, current_thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import shipments
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import Customer, IdempotencyRecord, Role, SalesOrder, Shipment, User
from app.schemas.sales import ShipmentIn
from app.services import package_workflows as package_workflow_service


@pytest.fixture(scope="module")
def shipment_reconciliation_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL shipment reconciliation races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Shipment reconciliation races require a loopback PostgreSQL URL without connection overrides")
    schema = f"shipment_reconcile_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with sessions() as db:
            user = User(
                name="Synthetic shipment reconciler",
                email=f"shipment-reconcile-{uuid4().hex}@example.test",
                password_hash="not-used",
                factory_code="MIL",
                extra_permissions=["storage.shipment"],
            )
            customer = Customer(name=f"Synthetic shipment customer {uuid4().hex}")
            db.add_all([user, customer])
            db.commit()
            user_id = int(user.id)
            customer_id = int(customer.id)
        yield sessions, user_id, customer_id
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _direct_manual_shipment(sessions, user_id, payload):
    with sessions() as db:
        try:
            return shipments.create_shipment(payload, db, db.get(User, user_id), None)
        except Exception as exc:
            db.rollback()
            return exc


def _direct_shipment_reconcile(sessions, user_id, payload, ready=None):
    with sessions() as db:
        if ready is not None:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
        try:
            return shipments.reconcile_manual_shipment(payload, db, db.get(User, user_id))
        except Exception as exc:
            db.rollback()
            return exc


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


def test_manual_shipment_reconciliation_tombstone_blocks_delayed_write():
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="fgs@example.com").one()
        customer = Customer(name=f"UI03 customer {uuid4().hex}")
        db.add(customer)
        db.commit()
        payload = ShipmentIn(manual=True, customer_id=customer.id, request_key=uuid4())

        assert shipments.reconcile_manual_shipment(payload, db, user) == {"status": "cancelled"}
        with pytest.raises(HTTPException) as rejected:
            shipments.create_shipment(payload, db, user, None)
        assert rejected.value.status_code == 409
        assert db.query(Shipment).filter_by(customer_id=customer.id).count() == 0
        record = db.query(IdempotencyRecord).filter_by(
            scope="shipments.create",
            key=str(payload.request_key),
        ).one()
        assert record.status_code == 409


def test_manual_shipment_reconciliation_hides_deleted_or_revoked_result():
    with SessionLocal() as db:
        role = Role(name=f"UI03 shipment {uuid4().hex}", permissions=["storage.shipment"])
        customer = Customer(name=f"UI03 shipment customer {uuid4().hex}")
        db.add_all([role, customer])
        db.flush()
        user = User(
            name="UI03 shipment operator",
            email=f"ui03-shipment-{uuid4().hex}@example.invalid",
            password_hash="unused",
            role_id=role.id,
            factory_code="MIL",
            extra_permissions=[],
        )
        db.add(user)
        db.commit()
        user_id = int(user.id)
        role_id = int(role.id)
        customer_id = int(customer.id)

    revoked_payload = ShipmentIn(manual=True, customer_id=customer_id, request_key=uuid4())
    with SessionLocal() as db:
        created = shipments.create_shipment(revoked_payload, db, db.get(User, user_id), None)
        revoked_shipment_id = int(created["id"])
    with SessionLocal() as db:
        db.get(Role, role_id).permissions = []
        db.commit()
    with SessionLocal() as db:
        resolution = shipments.reconcile_manual_shipment(
            revoked_payload,
            db,
            db.get(User, user_id),
        )
    assert resolution == {"status": "completed_unavailable"}
    with SessionLocal() as db:
        assert db.get(Shipment, revoked_shipment_id) is not None

    with SessionLocal() as db:
        db.get(Role, role_id).permissions = ["storage.shipment"]
        db.commit()
    deleted_payload = ShipmentIn(manual=True, customer_id=customer_id, request_key=uuid4())
    with SessionLocal() as db:
        created = shipments.create_shipment(deleted_payload, db, db.get(User, user_id), None)
        deleted_id = int(created["id"])
    with SessionLocal() as db:
        db.delete(db.get(Shipment, deleted_id))
        db.commit()
    with SessionLocal() as db:
        resolution = shipments.reconcile_manual_shipment(
            deleted_payload,
            db,
            db.get(User, user_id),
        )
    assert resolution == {"status": "completed_unavailable"}


def test_postgres_manual_shipment_commit_wins_reconciliation_race(
    shipment_reconciliation_postgres_sessions,
    monkeypatch,
):
    sessions, user_id, customer_id = shipment_reconciliation_postgres_sessions
    payload = ShipmentIn(manual=True, customer_id=customer_id, request_key=uuid4())
    original_locked = Event()
    release_original = Event()
    reconcile_ready = Queue()
    replay_original = shipments.replay_idempotent_response

    def delayed_replay(*args, **kwargs):
        if current_thread().name.startswith("shipment-original"):
            original_locked.set()
            assert release_original.wait(10), "Original shipment was not released"
        return replay_original(*args, **kwargs)

    monkeypatch.setattr(shipments, "replay_idempotent_response", delayed_replay)
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="shipment-original") as workers:
        original = workers.submit(_direct_manual_shipment, sessions, user_id, payload)
        assert original_locked.wait(10), "Original shipment did not acquire its manual advisory lock"
        reconciled = workers.submit(
            _direct_shipment_reconcile,
            sessions,
            user_id,
            payload,
            reconcile_ready,
        )
        reconcile_pid = reconcile_ready.get(timeout=10)
        try:
            with sessions() as inspector:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    blockers = inspector.execute(
                        text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": reconcile_pid},
                    ).scalar_one()
                    if blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Shipment reconciliation must wait for the in-flight original")
        finally:
            release_original.set()
        created = original.result(timeout=10)
        recovered = reconciled.result(timeout=10)

    assert not isinstance(created, Exception), created
    assert recovered == {"status": "completed", "result": jsonable_encoder(created)}
    with sessions() as db:
        assert db.query(Shipment).filter_by(customer_id=customer_id).count() == 1
        assert db.query(IdempotencyRecord).filter_by(
            scope="shipments.create",
            key=str(payload.request_key),
        ).count() == 1


def test_postgres_manual_shipment_cancel_wins_before_delayed_original(
    shipment_reconciliation_postgres_sessions,
    monkeypatch,
):
    sessions, user_id, customer_id = shipment_reconciliation_postgres_sessions
    payload = ShipmentIn(manual=True, customer_id=customer_id, request_key=uuid4())
    with sessions() as db:
        shipments_before = db.query(Shipment).filter_by(customer_id=customer_id).count()
    original_waiting = Event()
    release_original = Event()
    real_lock = package_workflow_service.lock_request

    def pause_original(db, lock_user_id, operation, key):
        if current_thread().name.startswith("delayed-shipment"):
            original_waiting.set()
            assert release_original.wait(10), "Delayed shipment was not released"
        return real_lock(db, lock_user_id, operation, key)

    monkeypatch.setattr(package_workflow_service, "lock_request", pause_original)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="delayed-shipment") as worker:
        original = worker.submit(_direct_manual_shipment, sessions, user_id, payload)
        assert original_waiting.wait(10), "Original shipment did not reach the pre-lock pause"
        try:
            cancelled = _direct_shipment_reconcile(sessions, user_id, payload)
        finally:
            release_original.set()
        delayed = original.result(timeout=10)

    assert cancelled == {"status": "cancelled"}
    assert isinstance(delayed, HTTPException)
    assert delayed.status_code == 409
    with sessions() as db:
        assert db.query(Shipment).filter_by(customer_id=customer_id).count() == shipments_before
        record = db.query(IdempotencyRecord).filter_by(
            scope="shipments.create",
            key=str(payload.request_key),
        ).one()
        assert record.status_code == 409
        assert package_workflow_service.is_cancelled_request(record.response_json)
