from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Department, Model, Package, PackagingRecord, ProductionOrder, WorkOrder
from app.services import packages as package_service


@pytest.fixture(scope="module")
def package_write_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL through the disposable PostgreSQL launcher")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Package-write races require loopback PostgreSQL without connection overrides")

    schema = f"package_write_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
        pool_size=5,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed_packaged_order(sessions, quantity: int) -> tuple[int, int]:
    marker = uuid4().hex[:10]
    with sessions.begin() as db:
        department = db.query(Department).filter_by(code="PKG").one_or_none()
        if department is None:
            department = Department(name="Packaging", code="PKG")
            db.add(department)
            db.flush()
        model = Model(
            code=f"PERF09-PG-{marker}",
            name=f"PERF09 PostgreSQL {marker}",
            product_type="shirt",
        )
        db.add(model)
        db.flush()
        order = ProductionOrder(
            production_no=f"PERF09-PG-PO-{marker}",
            production_type="branded_stock",
            source_type="usluga",
            model_id=model.id,
            status="packaging",
            planned_quantity=quantity,
        )
        db.add(order)
        db.flush()
        work_order = WorkOrder(
            production_order_id=order.id,
            department_id=department.id,
            operation="packaging",
            status="completed",
            planned_input_qty=quantity,
            planned_output_qty=quantity,
            actual_input_qty=quantity,
            actual_output_qty=quantity,
            passed_qty=quantity,
        )
        db.add(work_order)
        db.flush()
        db.add(PackagingRecord(
            work_order_id=work_order.id,
            input_qty=quantity,
            packed_qty=quantity,
            package_count=quantity,
            total_packed_quantity=quantity,
        ))
        return int(order.id), int(model.id)


def _package_kwargs(order_id: int, model_id: int) -> dict:
    return {
        "production_order_id": order_id,
        "model_id": model_id,
        "color": "navy",
        "items": [{
            "model_id": model_id,
            "color": "navy",
            "size": "M",
            "quantity": 1,
        }],
        "capacity": 1,
        "packaging_department_code": "PKG",
    }


def _stub_package_side_effects(monkeypatch) -> None:
    monkeypatch.setattr(package_service, "save_qr_image", lambda *_args, **_kwargs: "/test/qr.png")
    monkeypatch.setattr(package_service, "save_barcode_image", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(package_service, "sync_production_order_status", lambda *_args, **_kwargs: None)


def test_postgres_bulk_and_scalar_share_order_then_number_lock_order(
    package_write_postgres_sessions,
    monkeypatch,
):
    sessions, engine = package_write_postgres_sessions
    order_id, model_id = _seed_packaged_order(sessions, 2)
    _stub_package_side_effects(monkeypatch)
    scalar_order_locked = Event()
    release_scalar = Event()
    scalar_pid: Queue[int] = Queue()
    bulk_pid: Queue[int] = Queue()

    def create_scalar() -> str:
        with sessions() as db:
            connection = db.connection()
            scalar_pid.put(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            paused = False

            def pause_after_order_lock(
                _connection,
                _cursor,
                statement,
                _parameters,
                _context,
                _executemany,
            ):
                nonlocal paused
                normalized = " ".join(statement.lower().split())
                if not paused and " from production_orders " in normalized and " for update" in normalized:
                    paused = True
                    scalar_order_locked.set()
                    assert release_scalar.wait(10)

            event.listen(connection, "after_cursor_execute", pause_after_order_lock)
            try:
                package = package_service.create_package(db, **_package_kwargs(order_id, model_id))
                db.commit()
                return str(package.package_no)
            finally:
                event.remove(connection, "after_cursor_execute", pause_after_order_lock)

    def create_bulk() -> str:
        with sessions() as db:
            bulk_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            package = package_service.create_packages_bulk(
                db,
                count=1,
                **_package_kwargs(order_id, model_id),
            )[0]
            db.commit()
            return str(package.package_no)

    with ThreadPoolExecutor(max_workers=2) as workers:
        scalar_future = workers.submit(create_scalar)
        assert scalar_order_locked.wait(10)
        scalar_backend_pid = scalar_pid.get(timeout=10)
        bulk_future = workers.submit(create_bulk)
        bulk_backend_pid = bulk_pid.get(timeout=10)
        try:
            deadline = monotonic() + 10
            with engine.connect() as observer:
                while monotonic() < deadline:
                    blockers = observer.execute(
                        text("SELECT pg_blocking_pids(:pid)"),
                        {"pid": bulk_backend_pid},
                    ).scalar_one()
                    if scalar_backend_pid in blockers:
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Bulk creation should wait for the scalar order-row lock")
        finally:
            release_scalar.set()
        package_numbers = [scalar_future.result(timeout=10), bulk_future.result(timeout=10)]

    assert len(set(package_numbers)) == 2
    with sessions() as db:
        persisted = db.query(Package.package_no).filter(
            Package.production_order_id == order_id,
        ).order_by(Package.package_no).all()
    assert [package_no for (package_no,) in persisted] == sorted(package_numbers)


def test_postgres_bulk_number_range_is_reused_after_rollback(
    package_write_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = package_write_postgres_sessions
    order_id, model_id = _seed_packaged_order(sessions, 2)
    _stub_package_side_effects(monkeypatch)

    with sessions() as db:
        rolled_back = [
            package.package_no
            for package in package_service.create_packages_bulk(
                db,
                count=2,
                **_package_kwargs(order_id, model_id),
            )
        ]
        db.rollback()

    with sessions() as db:
        retried = [
            package.package_no
            for package in package_service.create_packages_bulk(
                db,
                count=2,
                **_package_kwargs(order_id, model_id),
            )
        ]
        db.commit()

    assert retried == rolled_back
    assert len(set(retried)) == 2
