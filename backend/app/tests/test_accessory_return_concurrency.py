import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api.routes import inventory as inventory_routes
from app.db.base import Base
from app.models import (
    AuditLog, IdempotencyRecord, Item, ManualAccessoryIssue, MaterialReservation,
    Model, ProductionOrder, ProductionOrderMaterial, StockBatch, StockMovement, User, Warehouse,
)
from app.models.order_reference import BusinessOrderAlias
from app.schemas.inventory import AccessoryReturnIn
from app.services.inventory import create_material_reservations, current_stock_for_item, lock_accessory_return_allowance
from app.tests.conftest import TestSessionLocal


def _stock(session_factory):
    marker = uuid4().hex[:12]
    with session_factory() as db:
        item = Item(sku=f"RETURN-RACE-{marker}", name="Return race item", category="accessory", unit="pcs")
        model = Model(code=f"RETURN-RACE-{marker}", name="Return race model")
        warehouses = [Warehouse(name=f"Return {marker}-{i}", type="accessory_storage") for i in range(2)]
        user = User(name="Synthetic receiver", email=f"return-{marker}@example.invalid", password_hash="unused", factory_code="MIL")
        db.add_all([item, model, user, *warehouses])
        db.flush()
        order = ProductionOrder(
            production_no=f"RETURN-RACE-{marker}", production_type="branded_stock",
            model_id=model.id, planned_quantity=10,
        )
        batch = StockBatch(
            item_id=item.id, batch_no=f"RETURN-RACE-{marker}", quantity=10, unit="pcs",
            warehouse_id=warehouses[0].id, qc_status="passed",
        )
        db.add_all([order, batch])
        db.flush()
        db.add_all([
            StockMovement(movement_type="receive", item_id=item.id, batch_id=batch.id,
                          to_warehouse_id=warehouses[0].id, quantity=20, unit="pcs"),
            StockMovement(movement_type="consume", item_id=item.id, batch_id=batch.id,
                          from_warehouse_id=warehouses[0].id, quantity=10, unit="pcs",
                          reference_type="ProductionOrder", reference_id=order.id),
        ])
        db.commit()
        return {"item_id": item.id, "order_id": order.id, "user_id": user.id, "batch_id": batch.id,
                "source_id": warehouses[0].id, "destination_id": warehouses[1].id}


def _payload(ids, quantity=7, batch_no="RETURNED"):
    return AccessoryReturnIn(
        production_order_id=ids["order_id"], item_id=ids["item_id"], batch_no=batch_no,
        quantity=quantity, unit="pcs", warehouse_id=ids["destination_id"], qc_status="passed",
    )


def _return(db, ids, payload, key):
    try:
        response = inventory_routes.collect_back_accessory(
            payload, db, current=db.get(User, ids["user_id"]), idempotency_key=key,
        )
        return 201, response
    except HTTPException as exc:
        db.rollback()
        return exc.status_code, exc.detail
    except SQLAlchemyError as exc:
        db.rollback()
        return "database_error", type(exc).__name__


def _assert_state(session_factory, ids, returned, count, key_count):
    with session_factory() as db:
        returns = db.query(StockMovement).filter_by(
            reference_type="ProductionOrderAccessoryReturn", reference_id=ids["order_id"],
        ).all()
        assert len(returns) == count
        assert sum(float(row.quantity) for row in returns) == returned
        assert db.query(StockBatch).filter_by(item_id=ids["item_id"]).count() == 1 + count
        assert db.query(AuditLog).filter_by(user_id=ids["user_id"], action="return_accessory").count() == count
        assert db.query(IdempotencyRecord).filter_by(user_id=ids["user_id"]).count() == key_count
        assert current_stock_for_item(db, ids["item_id"], ids["source_id"]) == 10
        assert current_stock_for_item(db, ids["item_id"], ids["destination_id"]) == returned
        assert current_stock_for_item(db, ids["item_id"]) == 10 + returned


@pytest.mark.parametrize("key", [None, "sequential-return"])
def test_sequential_accessory_return_retry_and_excess(key):
    ids = _stock(TestSessionLocal)
    with TestSessionLocal() as db:
        first = _return(db, ids, _payload(ids), key)
        assert first[0] == 201
    with TestSessionLocal() as db:
        retry = _return(db, ids, _payload(ids), key)
        assert retry == first if key else retry[0] == 409
    if key:
        with TestSessionLocal() as db:
            assert _return(db, ids, _payload(ids, quantity=6), key)[0] == 409
    with TestSessionLocal() as db:
        assert _return(db, ids, _payload(ids, quantity=4), None)[0] == 409
    _assert_state(TestSessionLocal, ids, returned=7, count=1, key_count=int(key is not None))


def test_accessory_return_failure_rolls_back_stock_and_key_before_retry(monkeypatch):
    ids = _stock(TestSessionLocal)
    original = inventory_routes.store_idempotent_response

    def fail_after_store(*args, **kwargs):
        original(*args, **kwargs)
        raise HTTPException(503, "Synthetic pre-commit failure")

    monkeypatch.setattr(inventory_routes, "store_idempotent_response", fail_after_store)
    with TestSessionLocal() as db:
        assert _return(db, ids, _payload(ids), "rollback-return")[0] == 503
    _assert_state(TestSessionLocal, ids, returned=0, count=0, key_count=0)
    monkeypatch.setattr(inventory_routes, "store_idempotent_response", original)
    with TestSessionLocal() as db:
        assert _return(db, ids, _payload(ids), "rollback-return")[0] == 201
    _assert_state(TestSessionLocal, ids, returned=7, count=1, key_count=1)


@pytest.fixture(scope="module")
def return_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL accessory return races")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Accessory return races require loopback PostgreSQL without connection overrides")
    schema = f"accessory_returns_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {StockBatch.__table__, StockMovement.__table__, ManualAccessoryIssue.__table__,
                  MaterialReservation.__table__, ProductionOrderMaterial.__table__,
                  AuditLog.__table__, IdempotencyRecord.__table__, BusinessOrderAlias.__table__}
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.parametrize("case", ["no_key", "different_key", "same_key", "changed_payload", "partial", "rollback", "other_order"])
def test_postgres_concurrent_returns_serialize_before_allowance_and_replay(return_postgres_engine, monkeypatch, case):
    engine = return_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _stock(session_factory)
    second_ids = _stock(session_factory) if case == "other_order" else ids
    marker = uuid4().hex
    first_key = None if case in {"no_key", "other_order"} else f"return-{marker}"
    second_key = f"other-{marker}" if case in {"different_key", "partial"} else first_key
    first_payload = _payload(ids, quantity=4 if case == "partial" else 7)
    second_payload = _payload(second_ids, quantity=6 if case in {"partial", "changed_payload"} else 7)
    first_read = Event()
    release_first = Event()
    second_read = Event()
    ready = Queue()
    original_summary = inventory_routes.accessory_issue_summary
    original_store = inventory_routes.store_idempotent_response

    def gated_summary(db, **kwargs):
        rows = original_summary(db, **kwargs)
        if db.info.get("return_worker") == "first":
            first_read.set()
            assert release_first.wait(12), "First return was not released"
        else:
            second_read.set()
        return rows

    def maybe_fail(db, **kwargs):
        original_store(db, **kwargs)
        if case == "rollback" and db.info.get("return_worker") == "first":
            raise HTTPException(503, "Synthetic pre-commit failure")

    monkeypatch.setattr(inventory_routes, "accessory_issue_summary", gated_summary)
    monkeypatch.setattr(inventory_routes, "store_idempotent_response", maybe_fail)

    def worker(name, payload, key, worker_ids):
        with session_factory() as db:
            db.info["return_worker"] = name
            if name == "second":
                ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return _return(db, worker_ids, payload, key)

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(worker, "first", first_payload, first_key, ids)
        second = None
        waited = False
        try:
            assert first_read.wait(10), "First return did not read its allowance"
            second = workers.submit(worker, "second", second_payload, second_key, second_ids)
            second_pid = ready.get(timeout=10)
            with engine.connect() as observer:
                deadline = monotonic() + 10
                while monotonic() < deadline:
                    waited = bool(observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": second_pid}).scalar_one())
                    if waited or second_read.is_set():
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Second return neither waited nor reached its allowance read")
        finally:
            release_first.set()
        first_result = first.result(timeout=10)
        assert second is not None
        second_result = second.result(timeout=10)

    expected = (503, 201) if case == "rollback" else (201, 201) if case in {"same_key", "partial", "other_order"} else (201, 409)
    with session_factory() as db:
        credited = sum(float(row.quantity) for row in db.query(StockMovement).filter_by(
            reference_type="ProductionOrderAccessoryReturn", reference_id=ids["order_id"],
        ))
        assert credited <= 10, f"Returns credited {credited} units against 10 issued"
    assert (first_result[0], second_result[0]) == expected
    if case == "other_order":
        assert not waited, "Unrelated production orders must not share the allowance lock"
        _assert_state(session_factory, second_ids, returned=7, count=1, key_count=0)
    else:
        assert waited, "The second request must wait on a real PostgreSQL transaction lock before reading/replay"
    if case == "same_key":
        assert first_result == second_result
    count = 2 if case == "partial" else 1
    _assert_state(session_factory, ids, returned=10 if case == "partial" else 7,
                  count=count, key_count=0 if case in {"no_key", "other_order"} else count)


def test_postgres_return_lock_is_reentrant_and_missing_order_stays_404(return_postgres_engine):
    session_factory = sessionmaker(bind=return_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _stock(session_factory)
    with session_factory() as db:
        lock_accessory_return_allowance(db, ids["order_id"])
        lock_accessory_return_allowance(db, ids["order_id"])
        assert _return(db, ids, _payload(ids), "reentrant-return")[0] == 201
    with session_factory() as db:
        assert _return(db, ids, _payload({**ids, "order_id": 2**40}), None)[0] == 404
    _assert_state(session_factory, ids, returned=7, count=1, key_count=1)


def test_postgres_return_does_not_hold_reservation_resource_or_order_row_locks(return_postgres_engine, monkeypatch):
    session_factory = sessionmaker(bind=return_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _stock(session_factory)
    first_read = Event()
    release_return = Event()
    original_summary = inventory_routes.accessory_issue_summary

    def gated_summary(db, **kwargs):
        rows = original_summary(db, **kwargs)
        first_read.set()
        assert release_return.wait(12)
        return rows

    monkeypatch.setattr(inventory_routes, "accessory_issue_summary", gated_summary)

    def return_worker():
        with session_factory() as db:
            return _return(db, ids, _payload(ids), None)

    def reservation_worker():
        with session_factory() as db:
            rows = create_material_reservations(
                db, production_order_id=ids["order_id"], user_id=ids["user_id"],
                lines=[{"item_id": ids["item_id"], "stock_batch_id": ids["batch_id"],
                        "warehouse_id": ids["source_id"], "reserved_quantity": 2, "unit": "pcs"}],
            )
            db.commit()
            return len(rows)

    with ThreadPoolExecutor(max_workers=2) as workers:
        returned = workers.submit(return_worker)
        try:
            assert first_read.wait(10)
            # Same PO/item: a reservation's batch/item/number locks and PO FK
            # must remain compatible while the return transaction is open.
            assert workers.submit(reservation_worker).result(timeout=8) == 1
        finally:
            release_return.set()
        assert returned.result(timeout=10)[0] == 201
    _assert_state(session_factory, ids, returned=7, count=1, key_count=0)
