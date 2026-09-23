"""Legacy piece reservations serialize stock balance changes."""

from concurrent.futures import ThreadPoolExecutor
import os
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

from app.api.routes.finished_goods import release, reserve
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageScanLog,
    SalesOrder,
    Shipment,
    ShipmentPackage,
    StockReservation,
    User,
)
from app.services.packages import mark_damaged, reserve_package, ship_package


def _legacy_stock():
    marker = uuid4().hex
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code=f"RSV-{marker}", name="Legacy reserve integrity", status="approved")
        order = SalesOrder(order_no=f"RSV-{marker}", order_type="branded_stock_sale", status="draft")
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="reserve-integrity",
            source_record_id=marker,
            source_checksum="c" * 64,
            source_payload={"quantity": 10},
            imported_by=user.id,
        )
        db.add_all([model, order, receipt])
        db.flush()
        package = Package(
            package_no=f"RSV-{marker}",
            barcode=f"RSV-{marker}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="blue",
            total_quantity=10,
            capacity=10,
            status="received_in_storage",
        )
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=10,
            available_qty=10,
            reserved_qty=0,
            sold_qty=0,
            status="available",
        )
        db.add(stock)
        db.commit()
        return {
            "package_id": package.id,
            "stock_id": stock.id,
            "sales_order_id": order.id,
        }


def _reserve_api(client, headers, fixture, quantity=4):
    return client.post(
        "/api/finished-goods/reserve",
        headers=headers,
        params={
            "stock_id": fixture["stock_id"],
            "quantity": quantity,
            "sales_order_id": fixture["sales_order_id"],
        },
    )


def test_legacy_reserve_locks_package_before_refreshing_stock(client, auth_headers):
    fixture = _legacy_stock()
    locks = []
    package_reads = []

    def capture_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and " from packages " in normalized:
            package_reads.append(normalized)

    def capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                locks.append((sql, state.load_options._populate_existing))

    event.listen(Session, "do_orm_execute", capture)
    event.listen(SessionLocal.kw["bind"], "before_cursor_execute", capture_sql)
    try:
        response = _reserve_api(client, auth_headers, fixture)
    finally:
        event.remove(Session, "do_orm_execute", capture)
        event.remove(SessionLocal.kw["bind"], "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    package_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF packages" in sql)
    stock_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF finished_goods_stock" in sql)
    assert package_lock < stock_lock
    assert locks[package_lock][1] and locks[stock_lock][1]
    assert len(package_reads) == 2
    assert "packages.manual_receipt_id" in package_reads[0]
    assert "packages.status" in package_reads[1]
    for statement in package_reads:
        for omitted in (
            "packages.qr_code_url",
            "packages.storage_cell",
            "packages.storage_shelf",
            "packages.notes",
        ):
            assert omitted not in statement


@pytest.fixture(scope="module")
def reserve_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL reserve concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Finished-goods concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"finished_goods_reserve_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = {
            AuditLog.__table__,
            FinishedGoodsStock.__table__,
            LegacyStockReceipt.__table__,
            Package.__table__,
            PackageScanLog.__table__,
            SalesOrder.__table__,
            Shipment.__table__,
            ShipmentPackage.__table__,
            StockReservation.__table__,
            User.__table__,
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


def _postgres_stock(session_factory, *, reserved_quantity=0):
    marker = uuid4().hex
    with session_factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        user = User(
            name="Reserve concurrency user",
            email=f"reserve-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["sales.orders"],
            is_active=True,
        )
        model = Model(code=f"RSV-PG-{marker}", name="PostgreSQL reserve model", status="approved")
        orders = [
            SalesOrder(
                order_no=f"RSV-PG-{marker}-{index}",
                order_type="branded_stock_sale",
                status="draft",
            )
            for index in range(2)
        ]
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="reserve-postgres",
            source_record_id=marker,
            source_checksum="d" * 64,
            source_payload={"quantity": 10},
        )
        db.add_all([user, model, receipt, *orders])
        db.flush()
        package = Package(
            package_no=f"RSV-PG-{marker}",
            barcode=f"RSV-PG-{marker}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="blue",
            total_quantity=10,
            capacity=10,
            status="received_in_storage",
        )
        db.add(package)
        db.flush()
        stock = FinishedGoodsStock(
            package_id=package.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=10,
            available_qty=10 - reserved_quantity,
            reserved_qty=reserved_quantity,
            sold_qty=0,
            status="available" if reserved_quantity < 10 else "reserved",
        )
        db.add(stock)
        db.flush()
        old_reservation_id = None
        if reserved_quantity:
            old_reservation = StockReservation(
                sales_order_id=orders[0].id,
                finished_goods_stock_id=stock.id,
                package_id=package.id,
                quantity=reserved_quantity,
                reserved_by=user.id,
            )
            db.add(old_reservation)
            db.flush()
            old_reservation_id = old_reservation.id
        return {
            "user_id": user.id,
            "package_id": package.id,
            "stock_id": stock.id,
            "order_ids": [order.id for order in orders],
            "old_reservation_id": old_reservation_id,
        }


def _wait_for_postgres_blockers(observer, worker_pids):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if all(
            bool(observer.execute(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid},
            ).scalar_one())
            for pid in worker_pids
        ):
            return
        sleep(0.02)
    pytest.fail("Workers did not reach the expected PostgreSQL package-row lock wait")


def _race_under_package_lock(sessions, package_id, workers_to_run):
    ready = Queue()
    start = Event()

    def wrapped(worker):
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Coordinator did not start worker"
            return worker(db)

    with sessions() as holder, ThreadPoolExecutor(max_workers=len(workers_to_run)) as pool:
        holder.query(Package).filter(Package.id == package_id).with_for_update(of=Package).one()
        futures = [pool.submit(wrapped, worker) for worker in workers_to_run]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_postgres_blockers(holder, worker_pids)
        finally:
            start.set()
            holder.rollback()
        return [future.result(timeout=10) for future in futures]


def _reserve_worker(fixture, order_index, quantity):
    def worker(db):
        try:
            reserve(
                fixture["stock_id"],
                quantity,
                fixture["order_ids"][order_index],
                db,
                db.get(User, fixture["user_id"]),
            )
            return 200
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code

    return worker


def test_postgres_competing_reserves_cannot_oversell(reserve_postgres_sessions):
    sessions = reserve_postgres_sessions
    fixture = _postgres_stock(sessions)

    statuses = _race_under_package_lock(
        sessions,
        fixture["package_id"],
        [_reserve_worker(fixture, 0, 6), _reserve_worker(fixture, 1, 6)],
    )

    assert sorted(statuses) == [200, 400]
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock.id,
        ).all()
        assert (stock.available_qty, stock.reserved_qty, stock.sold_qty) == (4, 6, 0)
        assert sum(row.quantity for row in reservations) == 6


def test_postgres_reserve_and_release_preserve_both_orders(reserve_postgres_sessions):
    sessions = reserve_postgres_sessions
    fixture = _postgres_stock(sessions, reserved_quantity=4)

    def release_worker(db):
        try:
            release(
                fixture["old_reservation_id"],
                db,
                db.get(User, fixture["user_id"]),
            )
            return 200
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code

    statuses = _race_under_package_lock(
        sessions,
        fixture["package_id"],
        [_reserve_worker(fixture, 1, 6), release_worker],
    )

    assert statuses == [200, 200]
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock.id,
        ).all()
        assert (stock.available_qty, stock.reserved_qty, stock.sold_qty) == (4, 6, 0)
        assert [(row.sales_order_id, row.quantity) for row in reservations] == [
            (fixture["order_ids"][1], 6),
        ]


def test_postgres_reserve_and_dispatch_never_recreate_stock(reserve_postgres_sessions):
    sessions = reserve_postgres_sessions
    fixture = _postgres_stock(sessions)

    def dispatch_worker(db):
        package = db.query(Package).filter(Package.id == fixture["package_id"]).with_for_update(
            of=Package,
        ).populate_existing().one()
        ship_package(db, package, fixture["user_id"])
        db.commit()
        return 200

    reserve_status, dispatch_status = _race_under_package_lock(
        sessions,
        fixture["package_id"],
        [_reserve_worker(fixture, 0, 4), dispatch_worker],
    )

    assert reserve_status in {200, 409}
    assert dispatch_status == 200
    with sessions() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 0, 0, 10, "sold",
        )
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock.id,
        ).all()
        assert sum(row.quantity for row in reservations) == (4 if reserve_status == 200 else 0)


def test_postgres_reserve_and_damage_keep_one_valid_state(reserve_postgres_sessions):
    sessions = reserve_postgres_sessions
    fixture = _postgres_stock(sessions)

    def damage_worker(db):
        try:
            mark_damaged(db, db.get(Package, fixture["package_id"]), fixture["user_id"])
            db.commit()
            return 200
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code

    reserve_status, damage_status = _race_under_package_lock(
        sessions,
        fixture["package_id"],
        [_reserve_worker(fixture, 0, 4), damage_worker],
    )

    assert sorted((reserve_status, damage_status)) == [200, 409]
    with sessions() as db:
        package = db.get(Package, fixture["package_id"])
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock.id,
        ).all()
        if reserve_status == 200:
            assert package.status == "received_in_storage"
            assert (stock.available_qty, stock.reserved_qty) == (6, 4)
            assert sum(row.quantity for row in reservations) == 4
        else:
            assert package.status == "damaged"
            assert (stock.available_qty, stock.reserved_qty) == (10, 0)
            assert reservations == []


def test_postgres_package_reserve_and_damage_keep_one_valid_state(reserve_postgres_sessions):
    sessions = reserve_postgres_sessions
    fixture = _postgres_stock(sessions)

    def reserve_worker(db):
        try:
            reserve_package(db, db.get(Package, fixture["package_id"]), fixture["user_id"])
            db.commit()
            return 200
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code

    def damage_worker(db):
        try:
            mark_damaged(db, db.get(Package, fixture["package_id"]), fixture["user_id"])
            db.commit()
            return 200
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code

    reserve_status, damage_status = _race_under_package_lock(
        sessions,
        fixture["package_id"],
        [reserve_worker, damage_worker],
    )

    assert sorted((reserve_status, damage_status)) == [200, 409]
    with sessions() as db:
        package = db.get(Package, fixture["package_id"])
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert package.status == ("reserved" if reserve_status == 200 else "damaged")
        assert (stock.available_qty, stock.reserved_qty) == (10, 0)
