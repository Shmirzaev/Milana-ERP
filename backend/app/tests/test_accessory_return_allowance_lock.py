"""ST06: concurrent accessory returns shared one unlocked issued allowance.

`returnable_quantity` is an aggregate rather than a row. The route reads the
order's issued movements plus its manual accessory issues, subtracts every
recorded return for that order and unit, and only then compares the request
against what is left. Nothing serialized that read against the return the request
itself records, so two concurrent requests each read the same full allowance and
together returned more than was ever issued.

The concurrency proof needs two independent real connections against PostgreSQL
because SQLite does not implement row locking, so a SQLite or mocked run proves
nothing about the shared allowance. Set STABILIZATION_POSTGRES_URL to run it.
"""

from concurrent.futures import ThreadPoolExecutor
import os
import threading
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import inventory as inventory_routes
from app.services.idempotency import bind_idempotency_identity
from app.db.base import Base
from app.models import (
    AuditLog,
    IdempotencyRecord,
    Item,
    ManualAccessoryIssue,
    Model,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    StockBatch,
    StockMovement,
    User,
    Warehouse,
)
from app.schemas.inventory import AccessoryReturnIn
from app.services.inventory import accessory_issue_summary

# The allowance read happens through this route-module name, so wrapping it
# parks a worker after its aggregate has been fetched and decided but before it
# inserts the return that shrinks the next worker's allowance.
ALLOWANCE_LOCK = "FOR NO KEY UPDATE OF production_orders"
ALLOWANCE_READ = "FROM stock_movements"

ISSUED = 10
REQUESTED = 7


@pytest.fixture(scope="module")
def accessory_return_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL accessory-return concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Accessory-return concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"accessory_return_lock_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=20000 -cstatement_timeout=25000"},
        pool_size=6,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            AuditLog.__table__,
            IdempotencyRecord.__table__,
            Item.__table__,
            ManualAccessoryIssue.__table__,
            Model.__table__,
            ProductionOrder.__table__,
            # ProductionOrder.materials is lazy="selectin", so loading the order
            # always reads these two child tables.
            ProductionOrderItem.__table__,
            ProductionOrderMaterial.__table__,
            StockBatch.__table__,
            StockMovement.__table__,
            User.__table__,
            Warehouse.__table__,
        }
        pending = list(tables)
        while pending:
            for foreign_key in pending.pop().foreign_keys:
                target = foreign_key.column.table
                if target not in tables:
                    tables.add(target)
                    pending.append(target)
        Base.metadata.create_all(engine, tables=list(tables))
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _postgres_case(session_factory, *, issued=ISSUED):
    """One accessory order with a single issued allowance and no returns yet."""
    marker = uuid4().hex
    with session_factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        user = User(
            name="Accessory return user",
            email=f"accessory-return-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=[],
            is_active=True,
        )
        item = Item(sku=f"ST06-ACC-{marker}", name=f"ST06 accessory {marker}", category="accessory", unit="pcs")
        model = Model(code=f"ST06-{marker}", name="ST06 accessory model", status="approved")
        warehouse = Warehouse(name=f"ST06 storage {marker}", type="accessory_storage")
        db.add_all([user, item, model, warehouse])
        db.flush()
        order = ProductionOrder(
            production_no=f"ST06-PO-{marker}",
            production_type="branded_stock",
            model_id=model.id,
            status="new",
            planned_quantity=10,
        )
        db.add(order)
        db.flush()
        # A single consume movement for the order is the whole issued allowance.
        db.add(StockMovement(
            movement_type="consume",
            item_id=int(item.id),
            quantity=issued,
            unit="pcs",
            reference_type="ProductionOrder",
            reference_id=int(order.id),
        ))
        db.flush()
        return {
            "marker": marker,
            "user_id": int(user.id),
            "item_id": int(item.id),
            "po_id": int(order.id),
            "warehouse_id": int(warehouse.id),
            "issued": issued,
        }


def _return_payload(case, index, *, quantity=REQUESTED):
    return AccessoryReturnIn(
        production_order_id=case["po_id"],
        item_id=case["item_id"],
        batch_no=f"ST06-RETURN-{case['marker']}-{index}",
        quantity=quantity,
        unit="pcs",
        warehouse_id=case["warehouse_id"],
        qc_status="passed",
    )


def _recorded_returns(session_factory, case):
    with session_factory() as db:
        return float(db.query(func.coalesce(func.sum(StockMovement.quantity), 0)).filter(
            StockMovement.movement_type == "return",
            StockMovement.reference_type == "ProductionOrderAccessoryReturn",
            StockMovement.reference_id == case["po_id"],
            StockMovement.item_id == case["item_id"],
        ).scalar() or 0)


def _race_two_returns(sessions, case, monkeypatch, *, observe_blockers=False):
    """Run two returns past their allowance reads, then let them both proceed.

    Each worker is held after its aggregate has been fetched and the allowance
    compared, and before it inserts the return that shrinks the other's
    allowance. If the shared allowance is locked one worker is still parked on
    that lock when the hold window closes, and the invariant assertions decide
    pass or fail. With `observe_blockers` the window instead reports which
    worker is waiting on a row lock held by the other.
    """
    arrived = Queue()
    pids = Queue()
    release = Event()
    local = threading.local()
    real_summary = inventory_routes.accessory_issue_summary

    def rendezvous_summary(db, **kwargs):
        rows = real_summary(db, **kwargs)
        if not getattr(local, "done", False):
            local.done = True
            arrived.put(local.pid)
            release.wait(timeout=30)
        return rows

    def worker(index):
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            user = db.get(User, case["user_id"])
            bind_idempotency_identity(db, user)
            local.pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            pids.put(local.pid)
            try:
                inventory_routes.collect_back_accessory(
                    payload=_return_payload(case, index),
                    db=db,
                    current=user,
                    idempotency_key=None,
                )
                db.commit()
                return "committed"
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    def blocked_report(worker_pids):
        blocked = []
        with sessions() as observer:
            for pid in worker_pids:
                blockers = observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                ).scalar_one()
                if blockers and any(int(other) in worker_pids for other in blockers):
                    blocked.append(pid)
        holder = arrived.get_nowait() if not arrived.empty() else None
        return blocked, holder

    monkeypatch.setattr(inventory_routes, "accessory_issue_summary", rendezvous_summary)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, index) for index in (0, 1)]
            worker_pids = [pids.get(timeout=10) for _ in futures]
            # Wait for both allowance reads to finish. On correct locking only one
            # worker gets this far, so the window is bounded rather than blocking.
            deadline = monotonic() + 3
            while arrived.qsize() < len(futures) and monotonic() < deadline:
                sleep(0.02)
            report = None
            if observe_blockers:
                sleep(0.2)
                report = blocked_report(worker_pids)
            sleep(0.2)
            release.set()
            outcomes = [future.result(timeout=30) for future in futures]
            return (outcomes, *report) if report else outcomes
    finally:
        release.set()
        monkeypatch.undo()


def test_concurrent_accessory_returns_cannot_exceed_the_issued_allowance(
    accessory_return_postgres_sessions, monkeypatch,
):
    """Two returns of 7 against 10 issued may not both be accepted.

    Each request compares itself against an aggregate that the other request
    shrinks, so without serialization both read the same 10 and both commit.
    """
    sessions = accessory_return_postgres_sessions
    case = _postgres_case(sessions)

    outcomes = _race_two_returns(sessions, case, monkeypatch)
    recorded = _recorded_returns(sessions, case)

    assert outcomes.count("committed") == 1, (
        f"concurrent accessory returns both passed the same unlocked allowance: "
        f"{recorded:g} returned against {case['issued']:g} issued (outcomes {outcomes})"
    )
    assert outcomes.count("committed") == 1 and outcomes.count(409) == 1, (
        f"the losing return must be rejected on the allowance, not fail some other way: {outcomes}"
    )
    assert recorded == REQUESTED, (
        f"concurrent returns recorded {recorded:g} against {case['issued']:g} issued: {outcomes}"
    )
    with sessions() as db:
        row = next(
            row for row in accessory_issue_summary(db, production_order_id=case["po_id"])
            if int(row["item_id"]) == case["item_id"] and str(row["unit"]) == "pcs"
        )
    assert row["returnable_quantity"] == case["issued"] - REQUESTED, (
        f"allowance left after one return is wrong: {row}"
    )


def test_second_concurrent_return_waits_on_the_shared_allowance_lock(
    accessory_return_postgres_sessions, monkeypatch,
):
    """The second return must be parked on the lock, not decide beside it.

    7 + 7 fits inside nothing, but the point here is the mechanism: while one
    worker holds the shared allowance the other backend must be waiting on the
    lock that worker holds.
    """
    sessions = accessory_return_postgres_sessions
    case = _postgres_case(sessions)

    outcomes, blocked, holder = _race_two_returns(sessions, case, monkeypatch, observe_blockers=True)

    assert holder is not None, "no worker reached the allowance read while holding the lock"
    assert len(blocked) == 1, (
        f"exactly one return must be parked on the shared allowance lock, got {blocked} "
        f"(outcomes {outcomes})"
    )
    assert holder not in blocked, (
        f"the worker that read the allowance should be the lock holder, but {holder} was "
        f"itself blocked; blocked {blocked}"
    )


def test_allowance_lock_is_narrow_and_precedes_validation_and_replay(
    accessory_return_postgres_sessions,
):
    """The lock is FOR NO KEY UPDATE on the order, taken before the aggregate read.

    `of=` keeps PostgreSQL locking only the order row, and `key_share=True` keeps
    the lock compatible with the FOR KEY SHARE that a concurrent
    production_order_id foreign-key insert takes on that same row.
    """
    sessions = accessory_return_postgres_sessions
    case = _postgres_case(sessions)
    statements = []

    def capture(state):
        if not state.is_select:
            return
        sql = str(state.statement.compile(dialect=postgresql.dialect()))
        statements.append((sql, bool(state.load_options._populate_existing)))

    with sessions() as db:
        event.listen(Session, "do_orm_execute", capture)
        try:
            user = db.get(User, case["user_id"])
            bind_idempotency_identity(db, user)
            inventory_routes.collect_back_accessory(
                payload=_return_payload(case, 0),
                db=db,
                current=user,
                idempotency_key=f"st06-{case['marker']}",
            )
            db.commit()
        finally:
            event.remove(Session, "do_orm_execute", capture)

    lock_indexes = [i for i, (sql, _) in enumerate(statements) if ALLOWANCE_LOCK in sql]
    read_indexes = [i for i, (sql, _) in enumerate(statements) if ALLOWANCE_READ in sql]

    assert lock_indexes, (
        f"the return path no longer locks the shared allowance: {[sql for sql, _ in statements]}"
    )
    assert read_indexes, f"the allowance read was not observed: {[sql for sql, _ in statements]}"
    assert lock_indexes[0] < read_indexes[0], (
        "the allowance lock must be taken before the allowance is validated"
    )
    assert statements[lock_indexes[0]][1], "the locked order row must be refetched, not served from the identity map"
