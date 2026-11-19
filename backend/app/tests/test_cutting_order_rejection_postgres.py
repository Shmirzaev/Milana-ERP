"""Owned loopback PostgreSQL: locks, retries, stale requests and atomic recovery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic

import pytest
from fastapi import HTTPException

from app.api.routes import production, production_extra
from app.libs.dto.production.production import CuttingRecordIn, QualityCheckIn, WorkOrderUpdate
from app.libs.dto.production.work_order_rejection_input import CuttingWorkOrderRejectIn
from app.models.production import cutting_rejection_service as service
from app.schemas import AuditLog, CuttingRecord, Notification, ProductionOrder, User, WorkOrder
from app.tests.test_planning_cutting_factory import make_order, route_snapshot
from app.tests.test_planning_cutting_factory_postgres import cutting_factory_postgres  # noqa: F401


def reject(db, uid, wid):
    return service.reject_cutting_order(db, wid, CuttingWorkOrderRejectIn(reason="QA reason"), db.get(User, uid))


@pytest.mark.parametrize("lock_stage", ["order", "cutting", "sewing"])
def test_rejection_busy_refuses_quickly_then_recovers(cutting_factory_postgres, lock_stage):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    with sessions() as holder, sessions() as contender:
        if lock_stage == "order": holder.query(ProductionOrder).filter_by(id=oid).with_for_update().one()
        else: holder.query(WorkOrder).filter_by(id=works[lock_stage]).with_for_update().one()
        started = monotonic()
        with pytest.raises(HTTPException) as refused:
            reject(contender, uid, works["cutting"])
        assert refused.value.status_code == 409
        assert monotonic() - started < 2
        assert not contender.in_transaction()
        with sessions() as reader:
            assert route_snapshot(reader, oid) == before
        holder.rollback()
        assert reject(contender, uid, works["cutting"]).status == "rejected"


def test_ten_competing_retries_write_once_and_recover(cutting_factory_postgres):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        # A distinct recipient proves retry notification deduplication as well.
        creator = User(name="QA creator", email=f"creator-{oid}@example.invalid", password_hash="unused", factory_code="MIL")
        db.add(creator); db.flush()
        creator_id = creator.id
        db.get(ProductionOrder, oid).created_by = creator_id
        db.commit()
    barrier = Barrier(10)
    def attempt():
        barrier.wait(timeout=10)
        with sessions() as db:
            actor = db.get(User, uid)
            try:
                service.reject_cutting_order(db, works["cutting"], CuttingWorkOrderRejectIn(reason="QA reason"), actor)
                return 200
            except HTTPException as error:
                assert not db.in_transaction()
                return error.status_code
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: attempt(), range(10)))
    assert set(results) <= {200, 409} and 200 in results
    with sessions() as db:
        assert reject(db, uid, works["cutting"]).block_reason == "QA reason"
        assert db.query(AuditLog).filter_by(entity_id=works["cutting"], action="reject_cutting").count() == 1
        assert db.query(Notification).filter_by(user_id=creator_id, link=f"/production-orders/{oid}").count() == 1
        assert db.query(CuttingRecord).filter_by(work_order_id=works["cutting"]).count() == 0
        for work in db.query(WorkOrder).filter_by(production_order_id=oid):
            assert work.actual_output_qty == 0
            if work.id != works["cutting"]: assert work.status == "waiting"


@pytest.mark.parametrize("mutation", ["start", "update", "cutting", "block", "unblock", "quality"])
def test_cached_work_order_cannot_write_after_rejection(cutting_factory_postgres, mutation):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records"])
    with sessions() as stale, sessions() as writer:
        cached = stale.get(WorkOrder, works["cutting"])
        assert cached.status == "in_progress"
        actor = stale.get(User, uid)
        reject(writer, uid, works["cutting"])
        with pytest.raises(HTTPException) as refused:
            if mutation == "start": production.start_wo(cached.id, stale, actor)
            elif mutation == "update": production.update_wo(cached.id, WorkOrderUpdate(actual_output_qty=1), stale, actor)
            elif mutation == "block": production_extra.block_wo(cached.id, production_extra.BlockIn(reason="overwrite"), stale, actor)
            elif mutation == "unblock": production_extra.unblock_wo(cached.id, stale, actor)
            elif mutation == "quality": production.post_quality(QualityCheckIn(work_order_id=cached.id, checked_qty=1, passed_qty=1, failed_qty=0), stale, actor)
            else: production.post_cutting(CuttingRecordIn(work_order_id=cached.id, cut_pieces=1, passed_pieces=1, input_quantity=0), stale, actor)
        assert refused.value.status_code == 409
        stale.rollback()
    with sessions() as db:
        assert db.get(WorkOrder, works["cutting"]).status == "rejected"
        assert db.query(CuttingRecord).filter_by(work_order_id=works["cutting"]).count() == 0


def test_notification_failure_rolls_back_flushed_rejection_and_audit(cutting_factory_postgres, monkeypatch):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        creator = User(name="QA creator", email=f"fault-{oid}@example.invalid", password_hash="unused", factory_code="MIL")
        db.add(creator); db.flush()
        db.get(ProductionOrder, oid).created_by = creator.id
        db.commit()
        before = route_snapshot(db, oid)
    original = service.notify
    def fail_after_flush(db, **kwargs):
        original(db, **kwargs)
        raise RuntimeError("injected notification failure")
    monkeypatch.setattr(service, "notify", fail_after_flush)
    with sessions() as db:
        with pytest.raises(RuntimeError, match="injected notification failure"):
            reject(db, uid, works["cutting"])
        assert not db.in_transaction()
    with sessions() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=works["cutting"], action="reject_cutting").count() == 0
        assert db.query(Notification).filter_by(link=f"/production-orders/{oid}").count() == 0
