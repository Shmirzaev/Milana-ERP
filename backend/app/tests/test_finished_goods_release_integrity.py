from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.finished_goods import release
from app.db.base import Base
from app.db.session import SessionLocal
from app.models import (
    AuditLog,
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageItem,
    PackageScanLog,
    Role,
    SalesOrder,
    Shipment,
    ShipmentPackage,
    StockReservation,
    User,
)
from app.services.packages import ship_package


def _legacy_reservation(client, headers, *, reserved_quantity=4):
    with SessionLocal() as db:
        token = uuid4().hex[:10]
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code=f"REL-{token}", name="Legacy release integrity", status="approved")
        order = SalesOrder(order_no=f"REL-{token}", order_type="branded_stock_sale", status="draft")
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="release-integrity",
            source_record_id=token,
            source_checksum="a" * 64,
            source_payload={"quantity": 10},
            imported_by=user.id,
        )
        db.add_all([model, order, receipt])
        db.flush()
        package = Package(
            package_no=f"REL-{token}",
            barcode=f"REL-{token}",
            legacy_receipt_id=receipt.id,
            model_id=model.id,
            color="blue",
            total_quantity=10,
            capacity=10,
            status="received_in_storage",
        )
        db.add(package)
        db.flush()
        db.add(PackageItem(
            package_id=package.id,
            model_id=model.id,
            color="blue",
            size="M",
            quantity=10,
        ))
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
        fixture = {
            "package_id": package.id,
            "stock_id": stock.id,
            "sales_order_id": order.id,
            "user_id": user.id,
        }

    response = client.post(
        "/api/finished-goods/reserve",
        headers=headers,
        params={
            "stock_id": fixture["stock_id"],
            "quantity": reserved_quantity,
            "sales_order_id": fixture["sales_order_id"],
        },
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        fixture["reservation_id"] = db.query(StockReservation.id).filter_by(
            sales_order_id=fixture["sales_order_id"],
            finished_goods_stock_id=fixture["stock_id"],
        ).scalar()
    return fixture


def _state(fixture):
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservation = db.get(StockReservation, fixture["reservation_id"])
        package = db.get(Package, fixture["package_id"])
        return (
            stock.quantity,
            stock.available_qty,
            stock.reserved_qty,
            stock.sold_qty,
            stock.status,
            reservation.quantity if reservation else None,
            package.status,
        )


def _reserve_another(client, headers, fixture, quantity):
    with SessionLocal() as db:
        order = SalesOrder(
            order_no=f"REL-{uuid4().hex[:10]}",
            order_type="branded_stock_sale",
            status="draft",
        )
        db.add(order)
        db.commit()
        order_id = order.id
    response = client.post(
        "/api/finished-goods/reserve",
        headers=headers,
        params={
            "stock_id": fixture["stock_id"],
            "quantity": quantity,
            "sales_order_id": order_id,
        },
    )
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        return db.query(StockReservation.id).filter_by(
            sales_order_id=order_id,
            finished_goods_stock_id=fixture["stock_id"],
        ).scalar()


def _reservation_balances(fixture):
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        reservations = db.query(StockReservation).filter_by(
            finished_goods_stock_id=stock.id,
        ).order_by(StockReservation.id).all()
        return (
            (stock.available_qty, stock.reserved_qty, stock.sold_qty),
            [(row.id, row.quantity) for row in reservations],
        )


def _release(client, headers, reservation_id):
    return client.post(
        "/api/finished-goods/release-reservation",
        headers=headers,
        params={"reservation_id": reservation_id},
    )


def test_release_short_circuits_unrepresentable_reservation_id_after_auth(client, auth_headers):
    class LookupForbidden:
        def get(self, *_args, **_kwargs):
            raise AssertionError("unrepresentable reservation ID must not reach the database")

    with pytest.raises(HTTPException) as exc_info:
        release(2_147_483_648, LookupForbidden(), current=None)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Reservation not found"

    path = "/api/finished-goods/release-reservation?reservation_id=2147483648"
    assert client.post(path).status_code == 401
    response = client.post(path, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Reservation not found"


def test_untouched_legacy_reservation_releases_once_with_ordered_locks(client, auth_headers):
    fixture = _legacy_reservation(client, auth_headers)
    locks = []

    def capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                locks.append((sql, state.load_options._populate_existing))

    event.listen(Session, "do_orm_execute", capture)
    try:
        response = _release(client, auth_headers, fixture["reservation_id"])
    finally:
        event.remove(Session, "do_orm_execute", capture)

    assert response.status_code == 200, response.text
    assert _state(fixture) == (10, 10, 0, 0, "available", None, "received_in_storage")
    package_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF packages" in sql)
    stock_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF finished_goods_stock" in sql)
    reservation_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF stock_reservations" in sql)
    assert package_lock < stock_lock < reservation_lock
    assert all(locks[i][1] for i in (package_lock, stock_lock, reservation_lock))

    retry = _release(client, auth_headers, fixture["reservation_id"])
    assert retry.status_code == 404
    assert _state(fixture) == (10, 10, 0, 0, "available", None, "received_in_storage")


def test_multiple_intact_reservations_release_only_the_selected_quantity(client, auth_headers):
    fixture = _legacy_reservation(client, auth_headers)
    second_reservation_id = _reserve_another(client, auth_headers, fixture, 6)

    first = _release(client, auth_headers, fixture["reservation_id"])

    assert first.status_code == 200, first.text
    assert _reservation_balances(fixture) == (
        (4, 6, 0),
        [(second_reservation_id, 6)],
    )
    second = _release(client, auth_headers, second_reservation_id)
    assert second.status_code == 200, second.text
    assert _reservation_balances(fixture) == ((10, 0, 0), [])


def test_consumed_old_reservation_cannot_borrow_another_orders_reserved_balance(
    client, auth_headers,
):
    fixture = _legacy_reservation(client, auth_headers)
    second_reservation_id = _reserve_another(client, auth_headers, fixture, 6)
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        stock.reserved_qty = 6
        stock.sold_qty = 4
        db.commit()

    before = _reservation_balances(fixture)
    assert before == (
        (0, 6, 4),
        [(fixture["reservation_id"], 4), (second_reservation_id, 6)],
    )
    old_release = _release(client, auth_headers, fixture["reservation_id"])
    current_release = _release(client, auth_headers, second_reservation_id)

    assert old_release.status_code == current_release.status_code == 409
    assert "consumed" in old_release.json()["detail"].lower()
    assert _reservation_balances(fixture) == before


@pytest.mark.parametrize("invalid_quantity", [0, -2], ids=["zero", "negative"])
def test_corrupt_nonpositive_legacy_reservation_fails_closed(
    client, auth_headers, invalid_quantity,
):
    fixture = _legacy_reservation(client, auth_headers)
    with SessionLocal() as db:
        db.execute(text("PRAGMA ignore_check_constraints = ON"))
        reservation = db.get(StockReservation, fixture["reservation_id"])
        reservation.quantity = invalid_quantity
        db.commit()
        db.execute(text("PRAGMA ignore_check_constraints = OFF"))

    before = _reservation_balances(fixture)
    response = _release(client, auth_headers, fixture["reservation_id"])

    assert response.status_code == 409, response.text
    assert "consumed" in response.json()["detail"].lower()
    assert _reservation_balances(fixture) == before


def test_shipped_legacy_reservation_cannot_restore_sold_stock(client, auth_headers):
    fixture = _legacy_reservation(client, auth_headers)
    with SessionLocal() as db:
        package = db.get(Package, fixture["package_id"])
        ship_package(db, package, fixture["user_id"])
        db.commit()

    before = _state(fixture)
    assert before == (10, 0, 0, 10, "sold", 4, "shipped")
    response = _release(client, auth_headers, fixture["reservation_id"])
    assert response.status_code == 409, response.text
    assert "shipped" in response.json()["detail"].lower()
    assert _state(fixture) == before


@pytest.mark.parametrize(
    ("reserved_qty", "sold_qty"),
    [(2, 2), (0, 4)],
    ids=["partially-consumed", "fully-consumed"],
)
def test_consumed_legacy_reservation_is_rejected_atomically(
    client, auth_headers, reserved_qty, sold_qty,
):
    fixture = _legacy_reservation(client, auth_headers)
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        stock.reserved_qty = reserved_qty
        stock.sold_qty = sold_qty
        db.commit()

    before = _state(fixture)
    assert before[1] + before[2] + before[3] == before[0]
    response = _release(client, auth_headers, fixture["reservation_id"])
    assert response.status_code == 409, response.text
    assert "consumed" in response.json()["detail"].lower()
    assert _state(fixture) == before


def test_release_rolls_back_cleanly_when_commit_fails(client, auth_headers, monkeypatch):
    fixture = _legacy_reservation(client, auth_headers)
    before = _state(fixture)
    with SessionLocal() as db:
        current = db.get(User, fixture["user_id"])

        def fail_commit():
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            release(fixture["reservation_id"], db, current)
        db.rollback()

    assert _state(fixture) == before
    assert _release(client, auth_headers, fixture["reservation_id"]).status_code == 200


def test_factory_access_policy_denial_blocks_release_without_mutation(client, auth_headers):
    fixture = _legacy_reservation(client, auth_headers)
    with SessionLocal() as db:
        role = Role(name=f"Release sales {uuid4().hex[:8]}", permissions=["sales.orders"])
        db.add(role)
        db.flush()
        user = db.query(User).filter_by(email="fgs@example.com").one()
        user.role_id = role.id
        user.extra_permissions = []
        user.access_policy = {"MIL": {"deny": ["sales.orders"]}}
        db.commit()

    token = client.post(
        "/api/auth/token",
        data={"username": "fgs@example.com", "password": "demo12345"},
    )
    assert token.status_code == 200, token.text
    denied_headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    before = _state(fixture)
    response = _release(client, denied_headers, fixture["reservation_id"])
    assert response.status_code == 403, response.text
    assert _state(fixture) == before


@pytest.fixture(scope="module")
def finished_goods_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL release concurrency coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Finished-goods concurrency tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"finished_goods_release_{uuid4().hex}"
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


def _postgres_reservation_case(session_factory):
    marker = uuid4().hex
    with session_factory.begin() as db:
        assert db.bind.dialect.name == "postgresql"
        user = User(
            name="Release concurrency user",
            email=f"release-{marker}@example.invalid",
            password_hash="unused",
            factory_code="MIL",
            extra_permissions=["sales.orders"],
            is_active=True,
        )
        model = Model(code=f"REL-PG-{marker}", name="PostgreSQL release model", status="approved")
        order = SalesOrder(order_no=f"REL-PG-{marker}", order_type="branded_stock_sale", status="draft")
        receipt = LegacyStockReceipt(
            source_system="TEST",
            source_warehouse_id="release-postgres",
            source_record_id=marker,
            source_checksum="b" * 64,
            source_payload={"quantity": 10},
        )
        db.add_all([user, model, order, receipt])
        db.flush()
        package = Package(
            package_no=f"REL-PG-{marker}",
            barcode=f"REL-PG-{marker}",
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
            available_qty=6,
            reserved_qty=4,
            sold_qty=0,
            status="available",
        )
        db.add(stock)
        db.flush()
        reservation = StockReservation(
            sales_order_id=order.id,
            finished_goods_stock_id=stock.id,
            package_id=package.id,
            quantity=4,
            reserved_by=user.id,
        )
        db.add(reservation)
        db.flush()
        return {
            "user_id": user.id,
            "package_id": package.id,
            "stock_id": stock.id,
            "reservation_id": reservation.id,
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
    pytest.fail("Workers did not reach the expected PostgreSQL row-lock wait")


def test_postgres_release_and_dispatch_never_recreate_sold_stock(finished_goods_postgres_sessions):
    sessions = finished_goods_postgres_sessions
    fixture = _postgres_reservation_case(sessions)
    ready = Queue()
    start = Event()

    def release_worker():
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Coordinator did not start release"
            try:
                release(fixture["reservation_id"], db, db.get(User, fixture["user_id"]))
                return 200
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code

    def dispatch_worker():
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Coordinator did not start dispatch"
            package = db.query(Package).filter(Package.id == fixture["package_id"]).with_for_update(
                of=Package,
            ).populate_existing().one()
            ship_package(db, package, fixture["user_id"])
            db.commit()
            return 200

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        assert holder.bind.dialect.name == "postgresql"
        holder.query(Package).filter(Package.id == fixture["package_id"]).with_for_update(of=Package).one()
        futures = [workers.submit(release_worker), workers.submit(dispatch_worker)]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_postgres_blockers(holder, worker_pids)
        finally:
            start.set()
            holder.rollback()
        release_status, dispatch_status = [future.result(timeout=10) for future in futures]

    assert release_status in {200, 409}
    assert dispatch_status == 200
    with sessions() as db:
        assert db.bind.dialect.name == "postgresql"
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 0, 0, 10, "sold",
        )
        assert db.get(Package, fixture["package_id"]).status == "shipped"
        assert db.query(StockReservation).filter_by(id=fixture["reservation_id"]).count() == (
            0 if release_status == 200 else 1
        )


def test_postgres_concurrent_release_retry_restores_stock_once(finished_goods_postgres_sessions):
    sessions = finished_goods_postgres_sessions
    fixture = _postgres_reservation_case(sessions)
    ready = Queue()
    start = Event()

    def release_worker():
        with sessions() as db:
            assert db.bind.dialect.name == "postgresql"
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            assert start.wait(10), "Coordinator did not start release"
            try:
                release(fixture["reservation_id"], db, db.get(User, fixture["user_id"]))
                return 200
            except HTTPException as rejected:
                db.rollback()
                return rejected.status_code

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        assert holder.bind.dialect.name == "postgresql"
        holder.query(Package).filter(Package.id == fixture["package_id"]).with_for_update(of=Package).one()
        futures = [workers.submit(release_worker) for _ in range(2)]
        try:
            worker_pids = [ready.get(timeout=10) for _ in futures]
            start.set()
            _wait_for_postgres_blockers(holder, worker_pids)
        finally:
            start.set()
            holder.rollback()
        statuses = [future.result(timeout=10) for future in futures]

    assert sorted(statuses) == [200, 404]
    with sessions() as db:
        assert db.bind.dialect.name == "postgresql"
        stock = db.get(FinishedGoodsStock, fixture["stock_id"])
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty, stock.status) == (
            10, 10, 0, 0, "available",
        )
        assert db.query(StockReservation).filter_by(id=fixture["reservation_id"]).count() == 0
