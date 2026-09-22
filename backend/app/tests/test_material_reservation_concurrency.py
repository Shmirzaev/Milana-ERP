import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from queue import Queue
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import cutting_passports
from app.db.base import Base
from app.models import (
    AuditLog, Item, MaterialReservation, Model, ProductionOrder, ProductionOrderMaterial, StockBatch, StockMovement, Warehouse,
)
from app.schemas.cutting_passport import CuttingPassportIn
from app.services import inventory, numbering
from app.tests.conftest import TestSessionLocal


def _stock(session_factory, *, item_count=1, warehouse_count=1):
    marker = uuid4().hex[:10]
    with session_factory() as db:
        model = Model(code=f"RES-{marker}", name="Reservation test model")
        warehouses = [Warehouse(name=f"Reservation {marker}-{i}", type="materials") for i in range(warehouse_count)]
        items = [Item(sku=f"RES-{marker}-{i}", name="Fabric", category="fabric", unit="kg") for i in range(item_count)]
        db.add_all([model, *warehouses, *items])
        db.flush()
        orders = [ProductionOrder(
            production_no=f"RES-{marker}-{i}", production_type="branded_stock", model_id=model.id, planned_quantity=10,
        ) for i in range(2)]
        batches = [StockBatch(
            item_id=item.id, warehouse_id=warehouse.id, batch_no=f"RES-{marker}-{item.id}-{warehouse.id}",
            quantity=10, unit="kg", qc_status="passed",
        ) for item in items for warehouse in warehouses]
        db.add_all([*orders, *batches])
        db.commit()
        return {
            "orders": [row.id for row in orders], "items": [row.id for row in items],
            "warehouses": [row.id for row in warehouses], "batches": [row.id for row in batches],
        }


def _line(ids, quantity, *, item=0, warehouse=0, batch=None):
    line = {"item_id": ids["items"][item], "reserved_quantity": quantity, "unit": "kg"}
    if warehouse is not None:
        line["warehouse_id"] = ids["warehouses"][warehouse]
    if batch is not None:
        line["stock_batch_id"] = ids["batches"][batch]
    return line


def _passport_payload(ids, reverse):
    batch_ids = list(reversed(ids["batches"])) if reverse else ids["batches"]
    return CuttingPassportIn(
        passport_no=f"RES-PASSPORT-{uuid4().hex[:10]}", date=datetime.now(timezone.utc),
        production_order_id=ids["orders"][0],
        materials=[{"stock_batch_id": batch_id} for batch_id in batch_ids],
        additional_materials=[
            {"stock_batch_id": batch_id, "estimated_quantity": 1, "unit": "kg"}
            for batch_id in batch_ids
        ],
    )


def _add_passport_materials(db, ids, payload):
    order = db.query(ProductionOrder).filter(
        ProductionOrder.id == ids["orders"][0],
    ).with_for_update(of=ProductionOrder).one()
    cutting_passports._add_passport_materials(
        db, order, SimpleNamespace(status="in_progress"), payload, SimpleNamespace(id=None),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_cutting_additions_reserve_together_and_retry_keeps_positions(monkeypatch, reverse):
    ids = _stock(TestSessionLocal, item_count=2)
    payload = _passport_payload(ids, reverse)
    calls = []
    original = cutting_passports.create_material_reservations

    def track_reservations(db, **kwargs):
        calls.append(kwargs["lines"])
        return original(db, **kwargs)

    monkeypatch.setattr(cutting_passports, "create_material_reservations", track_reservations)
    with TestSessionLocal() as db:
        _add_passport_materials(db, ids, payload)
        db.commit()
        assert len(calls) == 1, "All Cutting additions must acquire item locks before the first reservation number"
        assert len(calls[0]) == 2
        _add_passport_materials(db, ids, payload)
        db.commit()
        assert len(calls) == 1
        materials = db.query(ProductionOrderMaterial).filter_by(
            production_order_id=ids["orders"][0],
        ).order_by(ProductionOrderMaterial.position).all()
        assert [row.stock_batch_id for row in materials] == [row.stock_batch_id for row in payload.additional_materials]
        assert [row.position for row in materials] == [1, 2]
        assert db.query(MaterialReservation).filter_by(production_order_id=ids["orders"][0]).count() == 2
        assert db.query(AuditLog).filter_by(action="add_cutting_passport_material", entity_id=ids["orders"][0]).count() == 2


def test_cutting_additions_prefetch_existing_reservations_once():
    ids = _stock(TestSessionLocal, item_count=8, warehouse_count=1)
    payload = _passport_payload(ids, reverse=False)
    with TestSessionLocal() as db:
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "material_reservations" in statement.lower() and statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", capture)
        try:
            _add_passport_materials(db, ids, payload)
        finally:
            event.remove(db.bind, "before_cursor_execute", capture)
        existing_assignment_reads = [
            statement for statement in statements
            if "material_reservations.production_order_id" in statement.lower()
            and "material_reservations.stock_batch_id in (" in statement.lower()
        ]
        assert len(existing_assignment_reads) == 1


@pytest.mark.parametrize("batch_first", [False, True])
def test_mixed_batch_and_unbatched_reservations_keep_existing_allocation_rules(batch_first):
    ids = _stock(TestSessionLocal)
    lines = [_line(ids, 4, batch=0), _line(ids, 6)]
    if not batch_first:
        lines.reverse()
    with TestSessionLocal() as db:
        created = inventory.create_material_reservations(
            db, production_order_id=ids["orders"][0], lines=lines, user_id=None, source="planning",
        )
        db.commit()
        assert [float(row.reserved_quantity) for row in created] == [line["reserved_quantity"] for line in lines]
        assert {row.source for row in created} == {"planning"}
        assert inventory.current_stock_for_item(db, ids["items"][0]) == 10
        assert inventory.reserved_stock_for_item(db, ids["items"][0]) == 10


def test_unbatched_shortage_rejects_and_rollback_allows_retry():
    ids = _stock(TestSessionLocal)
    with TestSessionLocal() as db:
        with pytest.raises(HTTPException) as rejected:
            inventory.create_material_reservations(
                db, production_order_id=ids["orders"][0],
                lines=[_line(ids, 6), _line(ids, 5)], user_id=None,
            )
        assert rejected.value.status_code == 409
        db.rollback()
        assert inventory.reserved_stock_for_item(db, ids["items"][0]) == 0
        created = inventory.create_material_reservations(
            db, production_order_id=ids["orders"][0], lines=[_line(ids, 10)], user_id=None,
        )
        db.commit()
        assert len(created) == 1
        assert inventory.reserved_stock_for_item(db, ids["items"][0]) == 10


def test_batch_reservation_refreshes_cached_stock_before_availability_check():
    ids = _stock(TestSessionLocal)
    with TestSessionLocal() as db:
        cached = db.get(StockBatch, ids["batches"][0])
        with TestSessionLocal() as other:
            other.get(StockBatch, cached.id).quantity = 3
            other.commit()
        assert float(cached.quantity) == 10
        with pytest.raises(HTTPException) as rejected:
            inventory.create_material_reservations(
                db, production_order_id=ids["orders"][0], lines=[_line(ids, 5, batch=0)], user_id=None,
            )
        assert rejected.value.status_code == 409
        assert float(cached.quantity) == 3
        db.rollback()


def test_batch_reservation_keeps_pending_stock_changes_when_refreshing():
    ids = _stock(TestSessionLocal)
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, ids["batches"][0])
        batch.quantity = 3
        with pytest.raises(HTTPException) as rejected:
            inventory.create_material_reservations(
                db, production_order_id=ids["orders"][0], lines=[_line(ids, 5, batch=0)], user_id=None,
            )
        assert rejected.value.status_code == 409
        assert float(batch.quantity) == 3
        db.rollback()


@pytest.fixture(scope="module")
def reservation_postgres_engine():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL reservation concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Reservation concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"reservation_concurrency_{uuid4().hex}"
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4, max_overflow=0, isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            MaterialReservation.__table__, StockBatch.__table__, StockMovement.__table__, ProductionOrderMaterial.__table__,
            AuditLog.__table__,
        }
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


@pytest.mark.parametrize("case", [
    "same_warehouse", "global", "separate_warehouses", "mixed", "reverse_batches", "reverse_items",
])
def test_postgres_concurrent_reservations_preserve_available_stock(reservation_postgres_engine, case):
    engine = reservation_postgres_engine
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    ids = _stock(
        session_factory, item_count=2 if case in {"reverse_batches", "reverse_items"} else 1,
        warehouse_count=2 if case == "separate_warehouses" else 1,
    )
    if case in {"reverse_batches", "reverse_items"}:
        first = [_line(ids, 5, item=index, batch=index if case == "reverse_batches" else None) for index in range(2)]
        requests = [first, list(reversed(first))]
    elif case == "mixed":
        requests = [[_line(ids, 5, batch=0)], [_line(ids, 5)]]
    elif case == "separate_warehouses":
        requests = [[_line(ids, 10, warehouse=0)], [_line(ids, 10, warehouse=1)]]
    else:
        requests = [[_line(ids, 10, warehouse=None if case == "global" else 0)] for _ in range(2)]
    ready = Queue()
    start = Event()

    def reserve(index):
        with session_factory() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Reservation workers were not started"
            try:
                created = inventory.create_material_reservations(
                    db, production_order_id=ids["orders"][index], lines=requests[index], user_id=None,
                )
                db.commit()
                return 201, len(created)
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code, 0

    with session_factory() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        numbering.next_material_reservation_no(holder)
        futures = [workers.submit(reserve, index) for index in range(2)]
        try:
            pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            deadline = monotonic() + 10
            while monotonic() < deadline:
                for future in futures:
                    if future.done():
                        result = future.result()
                        pytest.fail(f"Reservation completed before the numbering lock was released: {result}")
                if all(bool(holder.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one()) for pid in pids):
                    break
                sleep(0.02)
            else:
                pytest.fail("Both reservation transactions must reach an actual PostgreSQL lock wait")
        finally:
            start.set()
            holder.rollback()
        results = [future.result(timeout=10) for future in futures]

    expected = [201, 409] if case in {"same_warehouse", "global"} else [201, 201]
    assert sorted(status for status, _ in results) == expected
    with session_factory() as db:
        for item_id in ids["items"]:
            stock = inventory.current_stock_for_item(db, item_id)
            reserved = inventory.reserved_stock_for_item(db, item_id)
            assert reserved == stock
        reservations = db.query(MaterialReservation).filter(MaterialReservation.item_id.in_(ids["items"])).all()
        assert len(reservations) == sum(count for _, count in results)
        assert len({row.reservation_no for row in reservations}) == len(reservations)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("first_worker", ["cutting", "batchless"])
def test_postgres_cutting_additions_and_batchless_reservation_do_not_deadlock(
    reservation_postgres_engine, monkeypatch, reverse, first_worker,
):
    sessions = sessionmaker(bind=reservation_postgres_engine, autoflush=False, expire_on_commit=False)
    ids = _stock(sessions, item_count=2)
    payload = _passport_payload(ids, reverse)
    target_item = 0 if reverse else 1
    ready = Queue()
    first_number_locked = Event()
    release_first = Event()
    original = inventory.next_material_reservation_no

    def pause_first_number(db):
        number = original(db)
        if db.info.get("reservation_worker") == first_worker and not first_number_locked.is_set():
            first_number_locked.set()
            assert release_first.wait(10), "Coordinator did not release the first reservation-number lock"
        return number

    monkeypatch.setattr(inventory, "next_material_reservation_no", pause_first_number)

    def reserve(worker):
        with sessions() as db:
            db.info["reservation_worker"] = worker
            ready.put((worker, db.execute(text("SELECT pg_backend_pid()")).scalar_one()))
            if worker != first_worker:
                assert first_number_locked.wait(10), "First reservation did not acquire its numbering lock"
            if worker == "cutting":
                _add_passport_materials(db, ids, payload)
            else:
                inventory.create_material_reservations(
                    db, production_order_id=ids["orders"][1],
                    lines=[_line(ids, 1, item=target_item)], user_id=None,
                )
            db.commit()
            return worker

    with sessions() as observer, ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(reserve, worker) for worker in ("cutting", "batchless")]
        try:
            pids = dict(ready.get(timeout=10) for _ in futures)
            assert first_number_locked.wait(10), "First reservation did not reach the number stream"
            waiting_worker = "batchless" if first_worker == "cutting" else "cutting"
            deadline = monotonic() + 10
            while monotonic() < deadline:
                blockers = observer.execute(
                    text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[waiting_worker]},
                ).scalar_one()
                if pids[first_worker] in blockers:
                    break
                for future in futures:
                    if future.done():
                        pytest.fail(f"Reservation ended before the intended lock contention: {future.result()}")
                sleep(0.02)
            else:
                pytest.fail("Cutting and batchless reservations must reach an actual PostgreSQL lock wait")
        finally:
            release_first.set()
        assert sorted(future.result(timeout=10) for future in futures) == ["batchless", "cutting"]

    with sessions() as db:
        reservations = db.query(MaterialReservation).filter(MaterialReservation.item_id.in_(ids["items"])).all()
        assert len(reservations) == 3
        assert len({row.reservation_no for row in reservations}) == 3
        for index, item_id in enumerate(ids["items"]):
            assert inventory.current_stock_for_item(db, item_id) == 10
            assert inventory.reserved_stock_for_item(db, item_id) == (2 if index == target_item else 1)
        materials = db.query(ProductionOrderMaterial).filter_by(
            production_order_id=ids["orders"][0],
        ).order_by(ProductionOrderMaterial.position).all()
        assert [row.stock_batch_id for row in materials] == [row.stock_batch_id for row in payload.additional_materials]
        assert [row.position for row in materials] == [1, 2]
        assert db.query(AuditLog).filter_by(action="add_cutting_passport_material", entity_id=ids["orders"][0]).count() == 2
