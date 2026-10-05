"""ST11: item-only and mixed batched reservations share one item capacity lock.

`create_material_reservations` has two claim paths. The batched path locked the
`StockBatch` row; the item-only path locked nothing, and the batched path never
consulted item-scoped capacity. Two callers could therefore both read the same
free capacity and together claim more than the item physically holds.

The concurrency proof needs two independent real connections against PostgreSQL
because SQLite does not implement row locking, so a SQLite or mocked run proves
nothing about overclaim. Set STABILIZATION_POSTGRES_URL to run it.
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
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import (
    Item,
    MaterialReservation,
    Model,
    ProductionOrder,
    ProductionOrderItem,
    ProductionOrderMaterial,
    StockBatch,
    StockMovement,
    Warehouse,
)
from app.services.inventory import (
    ACTIVE_RESERVATION_STATUSES,
    create_material_reservations,
    current_stock_for_item,
    reserved_stock_for_item,
)

# The reservation-number stream is acquired strictly after both claim paths have
# read available capacity and strictly before either INSERT. Pausing there means
# both capacity reads have already completed and returned, so neither transaction
# can commit before the other has decided. Without this the race is timing
# dependent and can pass on the unfixed code.
RENDEZVOUS = "pg_advisory_xact_lock"
BATCH_LOCK = "FOR UPDATE OF stock_batches"
ITEM_LOCK = "FOR NO KEY UPDATE OF items"


@pytest.fixture(scope="module")
def reservation_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL reservation concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Reservation concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"reservation_overclaim_{uuid4().hex}"
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
            Item.__table__,
            MaterialReservation.__table__,
            Model.__table__,
            ProductionOrder.__table__,
            # ProductionOrder.materials is lazy="selectin", so loading the order
            # always reads these two child tables.
            ProductionOrderItem.__table__,
            ProductionOrderMaterial.__table__,
            StockBatch.__table__,
            StockMovement.__table__,
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


def _postgres_stock(session_factory, *, batch_quantity=10):
    marker = uuid4().hex
    with session_factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        warehouse = Warehouse(name=f"ST11 storage {marker}", type="fabric_storage")
        model = Model(code=f"ST11-{marker}", name="ST11 overclaim model", status="approved")
        db.add_all([warehouse, model])
        db.flush()
        item = Item(
            sku=f"ST11-FAB-{marker}",
            name=f"ST11 fabric {marker}",
            category="fabric",
            unit="kg",
            track_batch=True,
            is_active=True,
        )
        db.add(item)
        db.flush()
        batch = StockBatch(
            item_id=item.id,
            batch_no=f"ST11-B-{marker}",
            quantity=batch_quantity,
            unit="kg",
            warehouse_id=warehouse.id,
            cost_per_unit=0,
        )
        orders = [
            ProductionOrder(
                production_no=f"ST11-PO-{marker}-{index}",
                production_type="branded_stock",
                model_id=model.id,
                status="new",
                planned_quantity=10,
            )
            for index in range(2)
        ]
        db.add_all([batch, *orders])
        db.flush()
        return {
            "item_id": item.id,
            "batch_id": batch.id,
            "warehouse_id": warehouse.id,
            "order_ids": [order.id for order in orders],
            "unit": "kg",
        }


def _item_only_line(fixture, quantity):
    return {
        "item_id": fixture["item_id"],
        "warehouse_id": fixture["warehouse_id"],
        "reserved_quantity": quantity,
        "unit": fixture["unit"],
    }


def _batched_line(fixture, quantity):
    return {
        "item_id": fixture["item_id"],
        "stock_batch_id": fixture["batch_id"],
        "reserved_quantity": quantity,
        "unit": fixture["unit"],
    }


def _item_capacity(session_factory, fixture):
    with session_factory() as db:
        return (
            float(current_stock_for_item(db, fixture["item_id"])),
            float(reserved_stock_for_item(db, fixture["item_id"])),
            db.query(MaterialReservation).filter(
                MaterialReservation.item_id == fixture["item_id"],
                MaterialReservation.status.in_(ACTIVE_RESERVATION_STATUSES),
            ).count(),
        )


def _race_paths(sessions, fixture, workers, *, observe_blockers=False, ordered_start=False):
    """Run each worker past its capacity read, then let them all proceed.

    Both workers are held after their availability read and before their INSERT,
    so the two capacity reads genuinely overlap. If the shared item capacity is
    locked correctly one worker is still parked on that lock when the hold
    window closes, and the invariant assertions then decide pass or fail.

    With `observe_blockers` the window instead reports how many workers were
    waiting on another backend and which one was holding the lock.
    """
    arrived = Queue()
    pids = Queue()
    release = Event()
    local = threading.local()

    def pause_before_insert(state):
        if getattr(local, "done", False):
            return
        sql = str(state.statement.compile(dialect=postgresql.dialect()))
        if RENDEZVOUS not in sql:
            return
        local.done = True
        arrived.put(local.pid)
        release.wait(timeout=30)

    def wrapped(production_order_id, lines):
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            local.pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            pids.put(local.pid)
            try:
                create_material_reservations(
                    db,
                    production_order_id=production_order_id,
                    lines=lines,
                    user_id=None,
                )
                db.commit()
                return "committed"
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    def blocked_report(worker_pids):
        """Count workers parked on a row lock held by the other worker."""
        blocked = 0
        with sessions() as observer:
            for pid in worker_pids:
                blockers = observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                ).scalar_one()
                if blockers and any(int(other) in worker_pids for other in blockers):
                    blocked += 1
        # The worker that reached the hold point is the one holding the item lock.
        holder = arrived.get_nowait() if not arrived.empty() else None
        return blocked, holder

    event.listen(Session, "do_orm_execute", pause_before_insert)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(wrapped, fixture["order_ids"][0], workers[0])]
            if ordered_start:
                deadline = monotonic() + 10
                while arrived.empty() and monotonic() < deadline:
                    sleep(0.02)
                assert not arrived.empty(), "first worker did not reach its locked capacity read"
            futures.append(pool.submit(wrapped, fixture["order_ids"][1], workers[1]))
            # Wait for both capacity reads to finish. On correct locking only one
            # worker gets this far, so the window is bounded rather than blocking.
            deadline = monotonic() + 3
            while arrived.qsize() < len(futures) and monotonic() < deadline:
                sleep(0.02)
            report = None
            if observe_blockers:
                sleep(0.2)
                worker_pids = [pids.get(timeout=10) for _ in futures]
                report = blocked_report(worker_pids)
            sleep(0.2)
            release.set()
            outcomes = [future.result(timeout=30) for future in futures]
            return (outcomes, *report) if report else outcomes
    finally:
        release.set()
        event.remove(Session, "do_orm_execute", pause_before_insert)


def test_mixed_paths_contend_on_one_shared_item_capacity_lock(
    reservation_postgres_sessions,
):
    """The batched path must wait on the same item lock as the item-only path.

    While one worker holds shared item capacity, the other must wait before
    checking its batch, warehouse and global capacity against committed claims.
    """
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=100)
    outcomes, blocked, holder = _race_paths(
        sessions,
        fixture,
        workers=[
            [_item_only_line(fixture, 5)],
            [_batched_line(fixture, 5)],
        ],
        observe_blockers=True,
    )

    assert blocked == 1, (
        f"the mixed batched path did not wait on the shared item capacity lock "
        f"(blocked workers {blocked}, outcomes {outcomes})"
    )
    assert holder is not None, "no worker reached the capacity read while holding the item lock"
    # 5 + 5 is inside the item's 100, so the wait is a lock wait and not a
    # capacity rejection.
    assert outcomes.count("committed") == 2, f"both paths should fit the item: {outcomes}"


def test_item_only_paths_cannot_overclaim_shared_item_capacity(reservation_postgres_sessions):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)

    outcomes = _race_paths(
        sessions,
        fixture,
        workers=[
            [_item_only_line(fixture, 10)],
            [_item_only_line(fixture, 10)],
        ],
    )

    _, reserved, _ = _item_capacity(sessions, fixture)
    assert reserved <= 10 + 1e-9, (
        f"Concurrent item-only reservations overclaimed item #{fixture['item_id']}: "
        f"{reserved:g} reserved against 10 on hand (outcomes {outcomes})"
    )


def _captured_locks(sessions, fixture, lines):
    captured = []

    def capture(state):
        if not state.is_select:
            return
        sql = str(state.statement.compile(dialect=postgresql.dialect()))
        if BATCH_LOCK in sql or ITEM_LOCK in sql:
            captured.append((sql, bool(state.load_options._populate_existing)))

    with sessions.begin() as db:
        event.listen(Session, "do_orm_execute", capture)
        try:
            create_material_reservations(
                db,
                production_order_id=fixture["order_ids"][0],
                lines=lines,
                user_id=None,
            )
        finally:
            event.remove(Session, "do_orm_execute", capture)
    return captured


def test_mixed_reservation_locks_batch_before_item_with_narrow_item_mode(
    reservation_postgres_sessions,
):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=100)

    locks = _captured_locks(
        sessions,
        fixture,
        [_batched_line(fixture, 5), _item_only_line(fixture, 5)],
    )
    kinds = [BATCH_LOCK if BATCH_LOCK in sql else ITEM_LOCK for sql, _ in locks]

    assert BATCH_LOCK in kinds, f"batched reservation stopped locking its stock batch: {kinds}"
    assert ITEM_LOCK in kinds, f"mixed reservation stopped locking shared item capacity: {kinds}"
    assert kinds.index(BATCH_LOCK) < kinds.index(ITEM_LOCK), (
        f"item capacity must be locked after batch rows to match cutting callers: {kinds}"
    )
    assert all(populated for _, populated in locks), (
        f"locked rows must be refreshed so the capacity read is current: {locks}"
    )
    assert kinds.count(ITEM_LOCK) == 1, f"one item lock must cover every line: {kinds}"


def test_item_only_reservation_locks_shared_item_capacity(reservation_postgres_sessions):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=100)

    locks = _captured_locks(sessions, fixture, [_item_only_line(fixture, 5)])

    assert any(ITEM_LOCK in sql for sql, _ in locks), (
        f"item-only reservation must lock shared item capacity: {[sql for sql, _ in locks]}"
    )
    assert not any(BATCH_LOCK in sql for sql, _ in locks), (
        "item-only reservation has no batch row to lock"
    )


@pytest.mark.parametrize("batch_first", [False, True])
@pytest.mark.parametrize("unscoped_item", [False, True])
def test_mixed_claims_reject_overbooking_in_either_order(
    reservation_postgres_sessions, batch_first, unscoped_item,
):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    item_line = _item_only_line(fixture, 10)
    if unscoped_item:
        item_line.pop("warehouse_id")
    lines = [item_line, _batched_line(fixture, 10)]
    if batch_first:
        lines.reverse()
    with sessions.begin() as db:
        create_material_reservations(db, production_order_id=fixture["order_ids"][0], lines=lines[:1], user_id=None)
    with pytest.raises(HTTPException) as raised:
        with sessions.begin() as db:
            create_material_reservations(db, production_order_id=fixture["order_ids"][1], lines=lines[1:], user_id=None)
    assert raised.value.status_code == 409
    current, reserved, count = _item_capacity(sessions, fixture)
    assert (current, reserved, count) == (10, 10, 1)


@pytest.mark.parametrize("batch_first", [False, True])
@pytest.mark.parametrize("unscoped_item", [False, True])
def test_concurrent_mixed_claims_commit_only_one_stock_capacity(
    reservation_postgres_sessions, batch_first, unscoped_item,
):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    item_line = _item_only_line(fixture, 10)
    if unscoped_item:
        item_line.pop("warehouse_id")
    workers = [[item_line], [_batched_line(fixture, 10)]]
    if batch_first:
        workers.reverse()
    outcomes = _race_paths(sessions, fixture, workers, ordered_start=True)
    assert sorted(str(value) for value in outcomes) == ["409", "committed"]
    current, reserved, count = _item_capacity(sessions, fixture)
    assert (current, reserved, count) == (10, 10, 1)


@pytest.mark.parametrize("batch_first", [False, True])
def test_overbooked_mixed_payload_rolls_back_all_claims(reservation_postgres_sessions, batch_first):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    lines = [_item_only_line(fixture, 6), _batched_line(fixture, 6)]
    if batch_first:
        lines.reverse()
    with pytest.raises(HTTPException) as raised:
        with sessions.begin() as db:
            create_material_reservations(db, production_order_id=fixture["order_ids"][0], lines=lines, user_id=None)
    assert raised.value.status_code == 409
    assert _item_capacity(sessions, fixture) == (10, 0, 0)


@pytest.mark.parametrize("batch_first", [False, True])
def test_mixed_payload_can_use_capacity_exactly_once(reservation_postgres_sessions, batch_first):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    lines = [_item_only_line(fixture, 5), _batched_line(fixture, 5)]
    if batch_first:
        lines.reverse()
    with sessions.begin() as db:
        assert len(create_material_reservations(db, production_order_id=fixture["order_ids"][0], lines=lines, user_id=None)) == 2
    assert _item_capacity(sessions, fixture) == (10, 10, 2)


def _second_warehouse(sessions, fixture, quantity):
    with sessions.begin() as db:
        warehouse = Warehouse(name=f"ST11 other {uuid4().hex}", type="fabric_storage")
        db.add(warehouse)
        db.flush()
        batch = StockBatch(item_id=fixture["item_id"], batch_no=f"ST11-other-{uuid4().hex}",
                           quantity=quantity, unit="kg", warehouse_id=warehouse.id, cost_per_unit=0)
        db.add(batch)
        db.flush()
        return {**fixture, "batch_id": batch.id, "warehouse_id": warehouse.id}


def test_warehouse_limit_does_not_steal_other_warehouse_capacity(reservation_postgres_sessions):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    other = _second_warehouse(sessions, fixture, 100)
    with sessions.begin() as db:
        create_material_reservations(db, production_order_id=fixture["order_ids"][0],
                                     lines=[_item_only_line(fixture, 10)], user_id=None)
    with pytest.raises(HTTPException) as raised:
        with sessions.begin() as db:
            create_material_reservations(db, production_order_id=fixture["order_ids"][1],
                                         lines=[_batched_line(fixture, 1)], user_id=None)
    assert raised.value.status_code == 409
    with sessions.begin() as db:
        create_material_reservations(db, production_order_id=fixture["order_ids"][1],
                                     lines=[_batched_line(other, 100)], user_id=None)
    assert _item_capacity(sessions, fixture) == (110, 110, 2)


@pytest.mark.parametrize("batched", [False, True])
def test_global_claim_blocks_scoped_claims_across_warehouses(reservation_postgres_sessions, batched):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    _second_warehouse(sessions, fixture, 100)
    global_line = _item_only_line(fixture, 110)
    global_line.pop("warehouse_id")
    with sessions.begin() as db:
        create_material_reservations(db, production_order_id=fixture["order_ids"][0], lines=[global_line], user_id=None)
    with pytest.raises(HTTPException) as raised:
        with sessions.begin() as db:
            line = _batched_line(fixture, 1) if batched else _item_only_line(fixture, 1)
            create_material_reservations(db, production_order_id=fixture["order_ids"][1], lines=[line], user_id=None)
    assert raised.value.status_code == 409
    assert _item_capacity(sessions, fixture) == (110, 110, 1)


def test_consumed_and_released_quantities_are_not_claimed_twice(reservation_postgres_sessions):
    sessions = reservation_postgres_sessions
    fixture = _postgres_stock(sessions, batch_quantity=10)
    with sessions.begin() as db:
        claim = create_material_reservations(db, production_order_id=fixture["order_ids"][0],
                                            lines=[_item_only_line(fixture, 10)], user_id=None)[0]
        claim.consumed_quantity = 2
        claim.released_quantity = 3
        claim.status = "partially_consumed"
        db.get(StockBatch, fixture["batch_id"]).quantity = 8
    with sessions.begin() as db:
        create_material_reservations(db, production_order_id=fixture["order_ids"][1],
                                     lines=[_batched_line(fixture, 3)], user_id=None)
    with pytest.raises(HTTPException) as raised:
        with sessions.begin() as db:
            create_material_reservations(db, production_order_id=fixture["order_ids"][1],
                                         lines=[_batched_line(fixture, 1)], user_id=None)
    assert raised.value.status_code == 409
    assert _item_capacity(sessions, fixture) == (8, 8, 2)
