"""Batch restore atomicity and serialization on an approved migrated PostgreSQL target."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier, Event
from time import monotonic
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.libs.dto.inventory.stock_batch_restore_input import StockBatchRestoreIn
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, StockBatch, StockMovement, User, Warehouse
from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401
from app.tests.test_inventory_item_create_postgres import role_actor


def seed(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        item = Item(sku=f'RESTORE-{marker}', name=f'Restore {marker}', category='fabric', unit='kg', is_active=True)
        warehouse = Warehouse(name=f'Restore {marker}', type='fabric_storage')
        db.add_all([item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=marker, quantity=0,
                           unit='kg', qc_status='hold', archived_at=datetime.now(timezone.utc),
                           roll_weights_kg=[10], roll_lengths_m=[20], piece_count=1)
        db.add(batch)
        db.flush()
        return item.id, warehouse.id, batch.id


def payload():
    return StockBatchRestoreIn(quantity=Decimal('3.2500'), reason='Physical count')


def test_pg_batch_restore_audit_failure_rolls_back(customer_pg_sessions, monkeypatch):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.receive', 'inventory.materials_only'])
    item_id, _, batch_id = seed(sessions)
    original = stock_service.log_action
    calls = []

    def fail_after_flush(db, *args, **kwargs):
        calls.append(db)
        original(db, *args, **kwargs)
        db.flush()
        raise RuntimeError('injected after flush')

    monkeypatch.setattr(stock_service, 'log_action', fail_after_flush)
    with sessions() as db:
        before = db.get(StockBatch, batch_id)
        saved = (before.quantity, before.archived_at, before.archived_by, before.qc_status,
                 before.roll_weights_kg, before.roll_lengths_m, before.piece_count)
        with pytest.raises(RuntimeError, match='injected after flush'):
            stock_service.restore_material_batch(db, batch_id, payload(), db.get(User, actor_id))
        assert calls == [db]
        db.rollback()
    with sessions() as db:
        batch = db.get(StockBatch, batch_id)
        assert batch.item_id == item_id
        assert (batch.quantity, batch.archived_at, batch.archived_by, batch.qc_status,
                batch.roll_weights_kg, batch.roll_lengths_m, batch.piece_count) == saved
        assert db.query(StockMovement).filter_by(batch_id=batch_id).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='StockBatch', entity_id=batch_id).count() == 0


class GateSession(Session):
    def __init__(self, *args, reached, release, **kwargs):
        super().__init__(*args, **kwargs)
        self.reached, self.release = reached, release

    def commit(self):
        self.reached.set()
        assert self.release.wait(15), 'restore commit gate timed out'
        return super().commit()


def test_pg_batch_restore_concurrent_duplicate_serializes(customer_pg_sessions):
    sessions = customer_pg_sessions
    actor_id = role_actor(sessions, ['storage.receive', 'inventory.materials_only'])
    item_id, warehouse_id, batch_id = seed(sessions)
    barrier = Barrier(2, timeout=8)
    reached, release, second_ready = Event(), Event(), Event()
    pids = {}

    def worker(first):
        db = (GateSession(bind=sessions.kw['bind'], autoflush=False, expire_on_commit=False,
                          reached=reached, release=release) if first else sessions())
        with db:
            pids[first] = db.execute(sa.text('SELECT pg_backend_pid()')).scalar_one()
            barrier.wait()
            if not first:
                assert reached.wait(8), 'first restore did not reach commit'
                second_ready.set()
            return stock_service.restore_material_batch(db, batch_id, payload(), db.get(User, actor_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker, True)
        second = pool.submit(worker, False)
        try:
            assert second_ready.wait(8), 'second restore did not start'
            assert pids[True] != pids[False]
            deadline = monotonic() + 5
            while monotonic() < deadline:
                assert not second.done(), 'second restore did not wait for the first'
                with sessions() as observer:
                    blockers = observer.execute(sa.text('SELECT pg_blocking_pids(:pid)'),
                                                {'pid': pids[False]}).scalar_one()
                if pids[True] in blockers:
                    break
                Event().wait(0.02)
            else:
                pytest.fail('second restore did not block on the first backend')
        finally:
            release.set()
        assert first.result(timeout=15).id == batch_id
        with pytest.raises(HTTPException) as error:
            second.result(timeout=15)
        assert error.value.status_code == 409

    with sessions() as db:
        batch = db.get(StockBatch, batch_id)
        assert batch.quantity == Decimal('3.2500')
        assert batch.archived_at is None and batch.archived_by is None
        assert batch.qc_status == 'pending'
        assert batch.roll_weights_kg == [] and batch.roll_lengths_m == [] and batch.piece_count is None
        movement = db.query(StockMovement).filter_by(batch_id=batch_id).one()
        assert (movement.item_id, movement.to_warehouse_id, movement.quantity, movement.unit) == (
            item_id, warehouse_id, Decimal('3.2500'), 'kg')
        assert (movement.movement_type, movement.reference_type, movement.reference_id, movement.created_by) == (
            'return', 'StockBatchRestore', batch_id, actor_id)
        audit = db.query(AuditLog).filter_by(entity_type='StockBatch', entity_id=batch_id).one()
        assert audit.action == 'restore' and audit.user_id == actor_id
        assert audit.new_value_json['reason'] == 'Physical count'
