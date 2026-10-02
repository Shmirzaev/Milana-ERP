"""Real concurrent adjustment regression; isolated schema in local milana_test.

Run: S06_POSTGRES_URL=<local URL> python -m pytest -q backend/tests/test_stock_adjustment_postgres.py
This lives outside app/tests because that suite forcibly configures SQLite.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker


@pytest.mark.parametrize("operation", ["batch_delta", "absolute_target"])
def test_concurrent_stock_adjustments(operation):
    url = os.environ.get("S06_POSTGRES_URL")
    if not url:
        pytest.skip("S06_POSTGRES_URL required: this regression only runs on PostgreSQL")
    control = create_engine(url)
    assert control.dialect.name == "postgresql"
    assert control.url.host in {"localhost", "127.0.0.1"}
    assert control.url.database == "milana_test"
    schema = "s06_" + uuid4().hex
    with control.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=10000"})
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    from app.db.base import Base
    from app.models import Item, StockBatch, StockMovement, Warehouse, User
    from app.api.routes.inventory import _apply_batch_tracked_stock_adjustment, set_stock_quantity
    from app.schemas.inventory import StockQuantityAdjustmentIn

    first_read = Event()
    second_read = Event()
    release_first = Event()
    pids = {}

    def hold_read(conn, cursor, statement, parameters, context, executemany):
        if not statement.lstrip().upper().startswith("SELECT") or "FROM stock_batches" not in statement or "stock_batches.batch_no" not in statement:
            return
        name = current_thread().name
        if name == "s06-first" and not first_read.is_set():
            first_read.set()
            assert release_first.wait(10), "Coordinator did not release first transaction"
        elif name == "s06-second":
            second_read.set()

    try:
        Base.metadata.create_all(engine)
        with sessions() as db:
            item = Item(sku="S06", name="Concurrency fabric", category="fabric", unit="kg", track_batch=True)
            warehouse = Warehouse(name="S06", type="fabric_storage")
            db.add_all([item, warehouse]); db.flush()
            batch = StockBatch(item_id=item.id, batch_no="S06", quantity=100, unit="kg", cost_per_unit=1,
                               warehouse_id=warehouse.id, qc_status="passed")
            db.add(batch); db.commit()
            item_id, batch_id = item.id, batch.id
        event.listen(engine, "after_cursor_execute", hold_read)

        def adjust(name, amount):
            current_thread().name = name
            with sessions() as db:
                pids[name] = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
                if operation == "batch_delta":
                    result = _apply_batch_tracked_stock_adjustment(db, item=db.get(Item, item_id), delta=amount,
                                                                 movement_type="adjustment", user_id=None)
                    db.commit()
                    return float(result[0].quantity)
                result = set_stock_quantity(item_id, StockQuantityAdjustmentIn(quantity=100 + amount, unit="kg"),
                                            db, User(id=None, extra_permissions=[]), force=False)
                return result.delta

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(adjust, "s06-first", 10)
            assert first_read.wait(10)
            second = pool.submit(adjust, "s06-second", 20)
            # Old code reads the same quantity; fixed code waits on the row lock.
            deadline = time.monotonic() + 10
            overlapped = False
            while time.monotonic() < deadline:
                if second_read.is_set():
                    overlapped = True
                    break
                if "s06-second" in pids:
                    with control.connect() as conn:
                        blockers = conn.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["s06-second"]}).scalar_one()
                    if pids["s06-first"] in blockers:
                        overlapped = True
                        break
                time.sleep(0.01)
            release_first.set()
            assert overlapped, "Did not prove transactions overlapped"
            deltas = [first.result(timeout=15), second.result(timeout=15)]
        with sessions() as db:
            final = float(db.get(StockBatch, batch_id).quantity)
            movements = db.query(StockMovement).filter_by(item_id=item_id).all()
            ledger = sum(float(m.quantity) * (-1 if m.movement_type == "issue" else 1) for m in movements)
            print(f"PostgreSQL localhost:5433/milana_test {operation}: initial=100 final={final} deltas={deltas} ledger={ledger}")
            assert len(movements) == 2
            assert final == 100 + ledger, f"Lost update: on hand {final}, ledger expects {100 + ledger}"
            assert final == (130 if operation == "batch_delta" else 120)
    finally:
        release_first.set()
        engine.dispose()
        with control.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()
