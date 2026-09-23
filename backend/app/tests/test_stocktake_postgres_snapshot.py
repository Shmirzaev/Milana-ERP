import csv
import io
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import stocktake as stocktake_routes
from app.db.base import Base
from app.models import LegacyStockReceipt, Model, Package, User
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services.stocktake import package_snapshots


@pytest.fixture(scope="module")
def stocktake_postgres_sessions():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL stocktake snapshot coverage")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or url.query
    ):
        pytest.fail("Stocktake snapshot tests require a loopback PostgreSQL URL without overrides")

    schema = f"stocktake_snapshot_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"
        },
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed_live_stocktake(session_factory, *, row_count: int = 401) -> tuple[int, int, str]:
    marker = uuid4().hex
    with session_factory() as db:
        user = User(
            name="PERF33 PostgreSQL",
            email=f"perf33-{marker}@example.test",
            password_hash="synthetic-not-a-login",
        )
        model = Model(code=f"PERF33-{marker}", name="PostgreSQL stocktake snapshot")
        db.add_all([user, model])
        db.flush()

        receipts = [
            LegacyStockReceipt(
                source_system="PERF33",
                source_warehouse_id="postgres-snapshot",
                source_record_id=f"{marker}-{number}",
                source_checksum=(marker + str(number)).ljust(64, "0")[:64],
                source_payload={},
            )
            for number in range(2)
        ]
        db.add_all(receipts)
        db.flush()
        packages = [
            Package(
                package_no=f"PERF33-PG-{marker}-{number}",
                barcode=f"PERF33-PG-QR-{marker}-{number}",
                model_id=model.id,
                legacy_receipt_id=receipts[number].id,
                color="navy",
                total_quantity=10,
                capacity=10,
                storage_cell="A-01",
                storage_shelf="1",
                status="received_in_storage",
            )
            for number in range(2)
        ]
        db.add_all(packages)
        db.flush()
        snapshots = package_snapshots(db, [package.id for package in packages])

        count = WarehouseStocktake(
            request_key=str(uuid4()),
            title="PERF33 repeatable-read boundary",
            created_by=user.id,
        )
        db.add(count)
        db.flush()
        db.add_all([
            WarehouseStocktakeRow(
                stocktake_id=count.id,
                identity=f"synthetic:{number}",
                package_id=packages[0].id if number < 400 else packages[1].id,
                expected=True,
                category="expected",
                snapshot=snapshots[packages[0].id if number < 400 else packages[1].id],
            )
            for number in range(row_count)
        ])
        db.commit()
        return int(count.id), int(packages[1].id), snapshots[packages[1].id]["location"]


def _pause_after_first_package_snapshot(engine):
    first_snapshot = Event()
    writer_committed = Event()
    isolation_levels: list[str | None] = []
    package_snapshot_queries = 0

    def pause(_connection, _cursor, statement, _parameters, context, _executemany):
        nonlocal package_snapshot_queries
        normalized = " ".join(statement.lower().split())
        if not (
            normalized.startswith("select")
            and " from packages left outer join models " in normalized
            and "packages.id in" in normalized
        ):
            return
        package_snapshot_queries += 1
        if first_snapshot.is_set():
            return
        isolation_levels.append(context.execution_options.get("isolation_level"))
        first_snapshot.set()
        if not writer_committed.wait(timeout=10):
            raise AssertionError("Concurrent stocktake writer did not commit")

    event.listen(engine, "after_cursor_execute", pause)
    return first_snapshot, writer_committed, isolation_levels, lambda: package_snapshot_queries, pause


def _move_package(session_factory, package_id: int):
    with session_factory() as db:
        db.execute(
            update(Package)
            .where(Package.id == package_id)
            .values(storage_shelf="2")
        )
        db.commit()


def test_postgres_changed_detail_uses_one_repeatable_read_snapshot(stocktake_postgres_sessions):
    sessions, engine = stocktake_postgres_sessions
    count_id, changed_package_id, _old_location = _seed_live_stocktake(sessions)
    started, committed, isolation_levels, query_count, listener = _pause_after_first_package_snapshot(engine)

    def read_detail():
        with sessions() as db:
            # Simulate the authentication dependency's earlier READ COMMITTED query.
            assert db.execute(text("SELECT 1")).scalar_one() == 1
            result = stocktake_routes.detail(
                count_id,
                db,
                None,
                result="changed",
                q="",
                offset=0,
                limit=10,
            )
            return result, db.in_transaction()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_detail)
            assert started.wait(timeout=10), "The first live package batch was not read"
            _move_package(sessions, changed_package_id)
            committed.set()
            result, transaction_open = future.result(timeout=20)
    finally:
        committed.set()
        event.remove(engine, "after_cursor_execute", listener)

    assert isolation_levels == ["REPEATABLE READ"]
    assert query_count() == 4  # Two summary batches and two changed-detail batches.
    assert result["summary"]["changed"] == 0
    assert result["total"] == 0
    assert result["rows"] == []
    assert transaction_open is False


async def _stream_body(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.encode() if isinstance(chunk, str) else chunk)
    return b"".join(chunks)


def test_postgres_csv_keeps_snapshot_across_400_row_stream_boundary(stocktake_postgres_sessions):
    sessions, engine = stocktake_postgres_sessions
    count_id, changed_package_id, old_location = _seed_live_stocktake(sessions)
    started, committed, isolation_levels, query_count, listener = _pause_after_first_package_snapshot(engine)

    def read_export():
        with sessions() as db:
            assert db.execute(text("SELECT 1")).scalar_one() == 1
            response = stocktake_routes.export(count_id, db, None)
            body = anyio.run(_stream_body, response)
            return response, body, db.in_transaction()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(read_export)
            assert started.wait(timeout=10), "The first streamed package batch was not read"
            _move_package(sessions, changed_package_id)
            committed.set()
            response, body, transaction_open = future.result(timeout=20)
    finally:
        committed.set()
        event.remove(engine, "after_cursor_execute", listener)

    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
    assert response.media_type == "text/csv; charset=utf-8"
    assert len(rows) == 402  # 401 package rows and one totals footer.
    assert rows[-1]["Row type"] == "totals"
    assert rows[-2]["Current location"] == old_location
    assert rows[-2]["Changed during count"] == "False"
    assert isolation_levels == ["REPEATABLE READ"]
    assert query_count() == 2
    assert transaction_open is False

    with sessions() as db:
        assert db.get(Package, changed_package_id).storage_shelf == "2"


def test_postgres_csv_generator_close_releases_read_only_snapshot(
    stocktake_postgres_sessions,
    monkeypatch,
):
    sessions, _engine = stocktake_postgres_sessions
    count_id, _changed_package_id, _old_location = _seed_live_stocktake(sessions, row_count=1)
    captured = {}

    class CapturedStreamingResponse:
        def __init__(self, content, *, media_type, headers):
            captured.update(content=content, media_type=media_type, headers=headers)

    monkeypatch.setattr(stocktake_routes, "StreamingResponse", CapturedStreamingResponse)
    with sessions() as db:
        assert db.execute(text("SELECT 1")).scalar_one() == 1
        stocktake_routes.export(count_id, db, None)
        lines = captured["content"]
        assert next(lines).startswith("\ufeffCount,Completed,Result")
        assert db.execute(text("SHOW transaction_isolation")).scalar_one() == "repeatable read"
        assert db.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        assert db.in_transaction() is True
        lines.close()
        assert db.in_transaction() is False

    assert captured["media_type"] == "text/csv; charset=utf-8"
    assert captured["headers"]["Content-Disposition"].endswith(f'inventory-count-{count_id}.csv"')
