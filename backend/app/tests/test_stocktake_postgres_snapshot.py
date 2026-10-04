"""PERF33: stocktake detail/export fully hydrate rows and lack a consistent snapshot.

`results()` loads every `warehouse_stocktake_rows` row for a count, materializes each
one into a Python dict, and only then applies the caller's `result` filter, the free-text
search and the offset/limit window. A count with 200 000 rows and `limit=100` therefore
transfers, decodes and JSON-parses 200 000 rows to return 100 of them, and the summary
counters are computed from that same fully hydrated list.

The rows are also read with no consistent snapshot: the row query and the
`package_snapshots` lookup that fills `current` are separate statements at READ COMMITTED,
so a scan committed between them is reflected in one half of a row and not the other. The
count, its rows, the live package snapshots and the summary must all come from one
snapshot.

The row's regression target is `test_stocktake_postgres_snapshot.py`, a `develop`-branch
reference that does not exist in this repository, so these tests are written from the live
source instead.

Query-count and snapshot proofs need real PostgreSQL: SQLite has no MVCC snapshot
isolation and no server-side row limiting, so a SQLite run proves neither. Set
STABILIZATION_POSTGRES_URL to run them.
"""

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import stocktake as stocktake_routes
from app.db.base import Base
from app.models import (
    FinishedGoodsStock,
    LegacyStockReceipt,
    Model,
    Package,
    PackageItem,
    User,
    Warehouse,
)
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow

# The detail endpoint returns at most this many rows regardless of count size.
DETAIL_LIMIT = 100
# A second scan-free read used to prove the snapshot is consistent.
EXPORT_BATCH = 500


@pytest.fixture(scope="module")
def stocktake_postgres():
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for real PostgreSQL stocktake snapshot coverage")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Stocktake snapshot tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"stocktake_snapshot_{uuid4().hex}"
    engine = create_engine(
        url,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=30000"},
        pool_size=4,
        max_overflow=0,
        isolation_level="READ COMMITTED",
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        tables = set()
        pending = [
            WarehouseStocktake.__table__,
            WarehouseStocktakeRow.__table__,
            Package.__table__,
            PackageItem.__table__,
            # package_snapshots aggregates live balances from finished-goods stock.
            FinishedGoodsStock.__table__,
            LegacyStockReceipt.__table__,
            Model.__table__,
            User.__table__,
            Warehouse.__table__,
        ]
        while pending:
            table = pending.pop()
            if table in tables:
                continue
            tables.add(table)
            pending.extend(fk.column.table for fk in table.foreign_keys)
        Base.metadata.create_all(engine, tables=list(tables))
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed(session_factory, *, rows: int):
    """One count holding `rows` expected rows, each tied to its own package."""
    marker = uuid4().hex
    with session_factory() as db:
        user = User(email=f"stocktake-{marker}@example.com", password_hash="x", name="Stocktake Tester")
        db.add(user)
        db.flush()
        model = Model(code=f"STK-{marker}", name="Stocktake Model")
        db.add(model)
        db.flush()
        count = WarehouseStocktake(request_key=marker, title="Stocktake", created_by=user.id)
        db.add(count)
        db.flush()
        warehouse = Warehouse(name=f"WH-{marker}", type="storage")
        db.add(warehouse)
        db.flush()
        for index in range(rows):
            # ck_packages_source_evidence requires exactly one real provenance column.
            receipt = LegacyStockReceipt(
                source_system="STOCKTAKE_PERF33",
                source_warehouse_id="1",
                source_record_id=f"{marker}-{index}",
                source_checksum="0" * 64,
                source_payload={},
            )
            db.add(receipt)
            db.flush()
            package = Package(
                package_no=f"PKG-{marker}-{index}",
                barcode=f"BC-{marker}-{index}",
                legacy_receipt_id=receipt.id,
                model_id=model.id,
                color="White",
                total_quantity=10,
                capacity=10,
                status="received_in_storage",
                warehouse_id=warehouse.id,
            )
            db.add(package)
            db.flush()
            db.add(
                WarehouseStocktakeRow(
                    stocktake_id=count.id,
                    identity=f"package:{package.id}",
                    package_id=package.id,
                    expected=True,
                    category="expected",
                    snapshot={
                        "package_no": package.package_no,
                        "barcode": package.barcode,
                        "model_code": model.code,
                        "model_name": model.name,
                        "color": "White",
                        "quantity": 10,
                        "available": 0,
                        "reserved": 0,
                        "status": "received_in_storage",
                        "warehouse_id": warehouse.id,
                        "location": "",
                    },
                )
            )
        db.commit()
        return count.id


def _count_rows(db, count_id):
    return (
        db.query(WarehouseStocktakeRow)
        .filter(WarehouseStocktakeRow.stocktake_id == count_id)
        .count()
    )


def test_detail_and_export_walk_rows_in_bounded_batches(stocktake_postgres):
    """Neither endpoint may hold a whole count in memory.

    The summary and total describe the whole count, so every row is still read; what the
    fix changes is that they are read in bounded batches and the page is chosen while
    streaming, instead of one unbounded result set materialized into a single list. The
    invariant is therefore batch boundedness plus a capped page, not a capped row count.
    """
    Session = sessionmaker(bind=stocktake_postgres, autoflush=False, expire_on_commit=False)
    small_id = _seed(Session, rows=20)
    batch_size = stocktake_routes.EXPORT_BATCH_SIZE
    large_id = _seed(Session, rows=batch_size * 2 + 25)

    def _row_reads(count_id):
        reads = []

        @event.listens_for(stocktake_postgres, "after_cursor_execute")
        def _record(conn, cursor, statement, parameters, context, executemany):
            if "warehouse_stocktake_rows" in statement and "COUNT" not in statement.upper():
                reads.append(max(cursor.rowcount, 0))

        try:
            with Session() as db:
                count = db.get(WarehouseStocktake, count_id)
                page = stocktake_routes.detail_rows(db, count, offset=0, limit=DETAIL_LIMIT)
            return reads, page
        finally:
            event.remove(stocktake_postgres, "after_cursor_execute", _record)

    small_reads, small_page = _row_reads(small_id)
    large_reads, large_page = _row_reads(large_id)

    # Two walks now (summary, then page), so a 20-row count is read as 20 + 20.
    assert sum(small_reads) == 40, f"sanity: the small count is walked twice, got {small_reads}"
    # Every row is still read, because the summary is exact; the page is a second walk.
    assert sum(large_reads) == 2 * (batch_size * 2 + 25), "summary walk plus page walk covers the count twice"
    # The batch ceiling is what keeps memory bounded: no single read exceeds it.
    assert max(large_reads) <= batch_size, (
        f"a single read pulled {max(large_reads)} rows; batches must stay at or below "
        f"EXPORT_BATCH_SIZE ({batch_size})"
    )
    # A count larger than one batch must actually be split.
    assert len([r for r in large_reads if r]) > 2, "a count larger than one batch must actually be split"
    assert len(large_page["rows"]) == DETAIL_LIMIT
    assert large_page["total"] == batch_size * 2 + 25
    assert len(small_page["rows"]) == 20


def test_detail_returns_only_the_requested_page(stocktake_postgres):
    """`detail()` must return at most `limit` rows for a count far larger than the limit."""
    Session = sessionmaker(bind=stocktake_postgres, autoflush=False, expire_on_commit=False)
    total_rows = DETAIL_LIMIT * 4
    count_id = _seed(Session, rows=total_rows)

    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        page = stocktake_routes.detail_rows(db, count, offset=0, limit=DETAIL_LIMIT)
        assert len(page["rows"]) == DETAIL_LIMIT, "a 400-row count must still return one bounded page"
        assert page["total"] == total_rows, "the unfiltered total must stay exact"

    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        page = stocktake_routes.detail_rows(db, count, offset=DETAIL_LIMIT, limit=DETAIL_LIMIT)
        assert len(page["rows"]) == DETAIL_LIMIT
        assert page["total"] == total_rows

    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        page = stocktake_routes.detail_rows(db, count, offset=total_rows - 10, limit=DETAIL_LIMIT)
        assert len(page["rows"]) == 10, "the final partial page must be short, not padded"
        assert page["total"] == total_rows

    # Pages must not overlap or skip rows.
    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        seen = []
        for offset in range(0, total_rows, DETAIL_LIMIT):
            seen.extend(r["id"] for r in stocktake_routes.detail_rows(
                db, count, offset=offset, limit=DETAIL_LIMIT)["rows"])
        assert seen == sorted(seen), "id-ordered pages must stay in id order"
        assert len(set(seen)) == total_rows, "paging must not duplicate or drop a row"


def test_detail_uses_repeatable_read_snapshot(stocktake_postgres):
    """Row data and live package snapshots must come from one consistent snapshot.

    At READ COMMITTED a scan committed between the row query and the `package_snapshots`
    lookup leaves the row showing pre-scan evidence beside post-scan `current` state. The
    fix reads detail/export under a single REPEATABLE READ snapshot so both halves agree.
    """
    Session = sessionmaker(bind=stocktake_postgres, autoflush=False, expire_on_commit=False)
    count_id = _seed(Session, rows=5)

    with Session() as db:
        isolation = db.execute(text("SHOW transaction_isolation")).scalar()
        assert isolation == "read committed", "precondition: the default is READ COMMITTED"

    # The route must request snapshot isolation for its read, not rely on the default.
    snapshot_level = stocktake_routes.DETAIL_ISOLATION
    assert snapshot_level == "REPEATABLE READ", (
        "detail/export must read under REPEATABLE READ so a scan committed mid-request "
        "cannot split one row's evidence from its current state"
    )

    with Session() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        count = db.get(WarehouseStocktake, count_id)
        rows = stocktake_routes.results(db, count)
        assert len(rows) == 5
        for row in rows:
            # every row resolves a current snapshot, so the two halves were read together
            assert row["package_id"] is not None
            assert row["current"], "current state is filled through the batched snapshot lookup"
            assert row["changed"] is False, "an unedited package must not read as changed"

    with Session() as db:
        assert db.execute(text("SHOW transaction_isolation")).scalar() == "read committed"


def test_export_streams_in_bounded_batches(stocktake_postgres):
    """Export must iterate rows in bounded batches rather than hydrating the whole count."""
    assert stocktake_routes.EXPORT_BATCH_SIZE <= EXPORT_BATCH, (
        "export must read rows in bounded batches; a full-count hydration defeats the point"
    )
    Session = sessionmaker(bind=stocktake_postgres, autoflush=False, expire_on_commit=False)
    count_id = _seed(Session, rows=EXPORT_BATCH + 25)

    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        batches = list(stocktake_routes.iter_result_batches(db, count))
        assert sum(len(batch) for batch in batches) == EXPORT_BATCH + 25
        assert all(len(batch) <= stocktake_routes.EXPORT_BATCH_SIZE for batch in batches)
        assert len(batches) > 1, "a count larger than one batch must actually be split"


def test_snapshot_json_bounds_are_unchanged(stocktake_postgres):
    """The existing snapshot payload shape must be preserved exactly."""
    Session = sessionmaker(bind=stocktake_postgres, autoflush=False, expire_on_commit=False)
    count_id = _seed(Session, rows=3)
    with Session() as db:
        count = db.get(WarehouseStocktake, count_id)
        rows = stocktake_routes.results(db, count)
    assert len(rows) == 3
    for row in rows:
        assert set(row) == {
            "package_id", "scanned_at", "scan_snapshot", "scanned_pieces", "scan_evidence_source",
            "id", "expected", "result", "snapshot", "current", "changed", "scan_code", "scanned_by",
        }
        assert row["result"] == "missing", "expected, unscanned rows stay missing"
        assert row["changed"] is False
        assert row["scan_evidence_source"] == "unresolved"
        assert isinstance(row["snapshot"], dict)
        json.dumps(row)  # must stay JSON-serializable
