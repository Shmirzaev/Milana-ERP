"""Roll-weight save rollback and row-lock behavior on the approved PG target."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.libs.dto.inventory.stock_batch_roll_weights_input import StockBatchRollWeightsIn
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, StockBatch, User, Warehouse
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401
from app.tests.test_inventory_item_create_postgres import role_actor


def seed(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        item = Item(sku=f"ROLL-{marker}", name="Roll fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"Roll warehouse {marker}", type="fabric_storage")
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=marker,
                           quantity=30, unit="kg", qc_status="hold", piece_count=2,
                           roll_weights_kg=[10, 20], roll_lengths_m=[])
        db.add(batch)
        db.flush()
        return batch.id


def test_pg_failure_after_audit_flush_rolls_back(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["storage.items"])
    batch_id = seed(sessions)
    original = stock_service.log_action

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected roll-weight audit failure")

    monkeypatch.setattr(stock_service, "log_action", fail_after_audit)
    with sessions() as db:
        with pytest.raises(RuntimeError, match="injected roll-weight audit failure"):
            stock_service.save_batch_roll_weights(
                db, batch_id, StockBatchRollWeightsIn(roll_weights_kg=[12, 18]), db.get(User, actor_id)
            )
        db.rollback()
    with sessions() as db:
        batch = db.get(StockBatch, batch_id)
        assert (batch.piece_count, batch.roll_weights_kg, batch.roll_lengths_m) == (2, [10, 20], [])
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch_id).count() == 0
    chain(sessions)


class GateSession(Session):
    def __init__(self, *args, reached, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.reached = reached
        self.release = release

    def commit(self):
        self.reached.set()
        assert self.release.wait(15), "first save commit gate timed out"
        return super().commit()


def test_pg_saves_serialize_on_batch_row(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ["storage.items"])
    batch_id = seed(sessions)
    reached, release, second_started = Event(), Event(), Event()
    pids = {}

    def save(first):
        db = (GateSession(bind=sessions.kw["bind"], autoflush=False, expire_on_commit=False,
                          reached=reached, release=release) if first else sessions())
        with db:
            pids[first] = db.execute(sa.text("SELECT pg_backend_pid()")).scalar_one()
            actor = db.get(User, actor_id)
            if not first:
                assert reached.wait(8), "first save did not reach commit"
                second_started.set()
            weights = [12, 18] if first else [13, 17]
            return stock_service.save_batch_roll_weights(
                db, batch_id, StockBatchRollWeightsIn(roll_weights_kg=weights), actor
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(save, True)
        second = pool.submit(save, False)
        try:
            assert second_started.wait(8), "second save did not start"
            deadline = monotonic() + 5
            while monotonic() < deadline:
                assert not second.done(), "second save did not wait"
                with sessions() as observer:
                    blockers = observer.execute(sa.text("SELECT pg_blocking_pids(:pid)"),
                                                {"pid": pids[False]}).scalar_one()
                if pids[True] in blockers:
                    break
                Event().wait(0.02)
            else:
                pytest.fail("second save did not block on the first backend")
        finally:
            release.set()
        assert first.result(timeout=15) == batch_id
        assert second.result(timeout=15) == batch_id
    with sessions() as db:
        batch = db.get(StockBatch, batch_id)
        assert (batch.piece_count, batch.roll_weights_kg) == (2, [13, 17])
        rows = db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch_id,
                                            action="save_roll_weights").order_by(AuditLog.id).all()
        assert len(rows) == 2
        assert rows[0].old_value_json["roll_weights_kg"] == [10, 20]
        assert rows[0].new_value_json["roll_weights_kg"] == [12, 18]
        assert rows[1].old_value_json["roll_weights_kg"] == [12, 18]
        assert rows[1].new_value_json["roll_weights_kg"] == [13, 17]
    chain(sessions)
