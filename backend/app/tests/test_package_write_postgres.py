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
from app.models import packages_service as package_service


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


def test_second_grade_and_singles_race_for_same_accepted_piece(package_write_postgres_sessions, monkeypatch):
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import ProductionOrderItem, SewingRecord

    sessions, _ = package_write_postgres_sessions
    _stub_package_side_effects(monkeypatch)
    order_id, model_id = _seed_packaged_order(sessions, 1)
    with sessions.begin() as db:
        db.get(ProductionOrder, order_id).source_type = "standard"
        department = db.query(Department).filter_by(code="PKG").one()
        sew = WorkOrder(production_order_id=order_id, department_id=department.id,
                        operation="sewing", passed_qty=1, actual_output_qty=1)
        db.add(sew); db.flush()
        db.add(SewingRecord(work_order_id=sew.id, input_qty=1, sewn_qty=1, passed_qty=1,
                            size_quantities=[{"size": "M", "quantity": 1}]))
        db.add(ProductionOrderItem(production_order_id=order_id, model_id=model_id,
                                  color="navy", size="M", planned_quantity=1))
    barrier = Barrier(2)

    def allocate(kind):
        with sessions() as db:
            barrier.wait(timeout=10)
            try:
                package_service.create_package(db, **_package_kwargs(order_id, model_id),
                                               stock_kind=kind, weight_kg=0.2)
                db.commit()
                return "created"
            except HTTPException:
                db.rollback()
                return "rejected"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(allocate, ["first_grade", "second_grade"])) == ["created", "rejected"]
    with sessions() as db:
        packages = db.query(Package).filter_by(production_order_id=order_id).all()
        assert len(packages) == 1 and packages[0].total_quantity == 1


def test_second_grade_migration_roundtrip_and_live_stock_guard(package_write_postgres_sessions):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    sessions, engine = package_write_postgres_sessions
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0148_second_grade_packages.py"
    spec = importlib.util.spec_from_file_location("second_grade_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Use a dedicated schema so other module tests' second-grade stock cannot
    # affect migration eligibility.
    schema = "grade_migration_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        connection.exec_driver_sql("CREATE TABLE packages (stock_kind text NOT NULL, CONSTRAINT ck_packages_stock_kind CHECK (stock_kind IN ('standard','first_grade')))")
        connection.exec_driver_sql("INSERT INTO packages VALUES ('standard'), ('first_grade')")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade(); migration.downgrade(); migration.upgrade()
        assert connection.exec_driver_sql("SELECT stock_kind FROM packages ORDER BY stock_kind").scalars().all() == ["first_grade", "standard"]
        connection.exec_driver_sql("INSERT INTO packages VALUES ('second_grade')")
        with pytest.raises(RuntimeError, match="second-grade"):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM packages").scalar() == 3
        connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def test_packaging_size_save_waits_for_package_creation_and_rejects_stale_counts(
    package_write_postgres_sessions, monkeypatch,
):
    from fastapi import HTTPException
    from app.models import SewingRecord, ProductionOrderItem
    from app.api.routes.package_workflows import _size_entry_order, PackagingSizeEntryIn
    from app.models.first_grade_service import packaging_size_entry, save_packaging_size_entry
    sessions, engine = package_write_postgres_sessions
    order_id, model_id = _seed_packaged_order(sessions, 2)
    _stub_package_side_effects(monkeypatch)
    with sessions.begin() as db:
        db.get(ProductionOrder, order_id).source_type = "standard"
        department = Department(code=f"SZ{uuid4().hex[:8]}", name="Size evidence sewing")
        db.add(department); db.flush()
        wo = WorkOrder(production_order_id=order_id, department_id=department.id, operation="sewing")
        db.add(wo); db.flush()
        db.add(SewingRecord(work_order_id=wo.id, input_qty=2, sewn_qty=2, passed_qty=2, size_quantities=[]))
        db.add(ProductionOrderItem(production_order_id=order_id, model_id=model_id, color="navy", size="M", planned_quantity=2))
    with sessions() as db:
        state = packaging_size_entry(db, order_id, None)
    payload = PackagingSizeEntryIn(version=state["version"], sizes=[{"size": "M", "quantity": 2}])
    ready, release = Event(), Event()
    pids = Queue()

    def pack():
        with sessions() as db:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            db.query(ProductionOrder).filter_by(id=order_id).with_for_update().one()
            ready.set()
            assert release.wait(10)
            package_service.create_package(db, **_package_kwargs(order_id, model_id))
            db.commit()

    def save():
        with sessions() as db:
            pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            order = _size_entry_order(db, None, order_id, None, lock=True)
            with pytest.raises(HTTPException) as error:
                save_packaging_size_entry(db, order, None, payload, None)
            assert error.value.detail == "FIRST_GRADE_SIZE_STALE"
            db.rollback()

    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(pack)
        assert ready.wait(10)
        pack_pid = pids.get(timeout=10)
        saver = workers.submit(save)
        save_pid = pids.get(timeout=10)
        try:
            deadline = monotonic() + 10
            with engine.connect() as observer:
                while monotonic() < deadline:
                    if pack_pid in observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": save_pid}).scalar_one():
                        break
                    sleep(0.02)
                else:
                    pytest.fail("Size evidence must wait for the package writer's order lock")
        finally:
            release.set()
        writer.result(timeout=10)
        saver.result(timeout=10)
    with sessions() as db:
        assert db.get(ProductionOrder, order_id).packaging_size_breakdowns is None


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


@pytest.mark.parametrize("same_package", [False, True])
def test_warehouse_delete_serializes_output_and_retires_print_evidence(
    package_write_postgres_sessions, monkeypatch, same_package,
):
    """Concurrent warehouse deletions conserve output under PostgreSQL's label guard."""
    import ast
    from pathlib import Path
    from threading import Barrier
    from fastapi import HTTPException
    from app.models import User, PackagePrintRun, PackagePrintRunMember, FinishedGoodsStock
    from app.models.package_workflows_service import contents
    from app.models.warehouse_packages_service import delete_warehouse_package

    sessions, engine = package_write_postgres_sessions
    order_id, model_id = _seed_packaged_order(sessions, 2)
    _stub_package_side_effects(monkeypatch)
    with sessions.begin() as db:
        db.get(ProductionOrder, order_id).source_type = "standard"
        work = db.query(WorkOrder).filter_by(production_order_id=order_id, operation="packaging").one()
        record = db.query(PackagingRecord).filter_by(work_order_id=work.id).one()
        record.package_count = record.total_packed_quantity = 0
        actor = User(name="Warehouse test", email=f"warehouse-{uuid4().hex}@example.invalid", password_hash="unused")
        db.add(actor)
        db.flush()
        actor_id, record_id = actor.id, record.id
        packages = [package_service.create_package(db, **_package_kwargs(order_id, model_id)) for _ in range(2)]
        ids = [package.id for package in packages]
        for package in packages:
            package.status = "received_in_storage"
            for historical in (True, False):
                run = PackagePrintRun(run_no=f"QA-{uuid4().hex}", code=f"PACKRUN:{uuid4().hex}",
                                      package_ids=[package.id], deleted_package_ids=[], created_by=actor.id,
                                      packaging_department_code="PKG",
                                      superseded_at=package.created_at if historical else None)
                db.add(run)
                db.flush()
                db.add(PackagePrintRunMember(run_id=run.id, package_id=package.id, snapshot=contents(package)))
    # Execute the deployed guard function verbatim, without replaying schema changes.
    migration = Path(__file__).resolve().parents[2] / "alembic/versions/0146_payroll_qr_closure.py"
    tree = ast.parse(migration.read_text())
    upgrade = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade")
    guard = next(node.value for node in ast.walk(upgrade) if isinstance(node, ast.Constant)
                 and isinstance(node.value, str) and "CREATE OR REPLACE FUNCTION protect_printed_package_deletion" in node.value)
    with engine.begin() as connection:
        connection.exec_driver_sql(guard)
        connection.exec_driver_sql("CREATE TRIGGER warehouse_delete_qa BEFORE DELETE ON packages FOR EACH ROW EXECUTE FUNCTION protect_printed_package_deletion()")
    barrier = Barrier(2)
    def remove(pid):
        with sessions() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=10)
            try:
                result = delete_warehouse_package(db, actor, pid)
                db.commit()
                return result["deleted_count"]
            except HTTPException as error:
                db.rollback()
                return error.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(remove, pid) for pid in ([ids[0], ids[0]] if same_package else ids)]
            results = sorted(future.result(timeout=25) for future in futures)
        assert results == ([1, 404] if same_package else [1, 1])
        with sessions() as db:
            assert db.get(PackagingRecord, record_id).packed_qty == (1 if same_package else 0)
            assert db.query(Package).filter(Package.id.in_(ids)).count() == (1 if same_package else 0)
            assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).count() == (1 if same_package else 0)
            assert db.query(PackagePrintRunMember).filter(PackagePrintRunMember.package_id.in_(ids)).count() == 4
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER warehouse_delete_qa ON packages")
