"""Real PostgreSQL locks, stale-source writers, bounded races and recovery.

Only an explicitly configured loopback disposable database is accepted. This
fixture creates ORM tables in a unique synthetic schema; no Alembic runs.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import bundles, production
from app.db.base import Base
from app.libs.dto.planning.production_cutting_factory import ProductionCuttingFactoryIn
from app.libs.dto.production.production import CuttingRecordIn, QualityCheckIn
from app.libs.dto.packaging.tracking import BundleIn
from app.models.planning import cutting_factory_service as service
from app.schemas import AuditLog, Bundle, CuttingRecord, Department, ProductionOrder, QualityCheck, User, WorkOrder
from app.tests.test_planning_cutting_factory import make_order, route_snapshot


@pytest.fixture(scope="module")
def cutting_factory_postgres():
    raw_url = os.environ.get("PLANNING_CUTTING_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set PLANNING_CUTTING_POSTGRES_URL to an owned disposable loopback PostgreSQL database")
    url = make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Routing tests require a disposable loopback PostgreSQL URL without overrides")
    schema = f"planning_cutting_{uuid4().hex}"
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"},
                           pool_size=5, max_overflow=0, isolation_level="READ COMMITTED")
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False), engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def move(db, oid, uid, code="ECT"):
    return service.change_cutting_factory(db, oid, ProductionCuttingFactoryIn(cutting_department_code=code), db.get(User, uid))


@pytest.mark.parametrize("lock_stage", ["order", "cutting", "sewing"])
def test_conflicting_lock_refuses_quickly_and_recovers(cutting_factory_postgres, lock_stage):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    with sessions() as holder, sessions() as contender:
        if lock_stage == "order":
            holder.query(ProductionOrder).filter_by(id=oid).with_for_update().one()
        else:
            holder.query(WorkOrder).filter_by(id=works[lock_stage]).with_for_update().one()
        started = monotonic()
        with pytest.raises(HTTPException) as rejected:
            move(contender, oid, uid)
        assert rejected.value.status_code == 409
        assert monotonic() - started < 2
        assert not contender.in_transaction()
        holder.rollback()
        assert move(contender, oid, uid).changed is True
    with sessions() as db:
        after = route_snapshot(db, oid)
        for original, current in zip(before, after):
            allowed = {"department_id", "updated_at"} if original["id"] == works["cutting"] else set()
            assert {key for key in original if original[key] != current[key]} <= allowed
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 1


def test_bounded_competing_retries_change_once_each_round(cutting_factory_postgres):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    def attempt(target, barrier):
        with sessions() as db:
            user = db.get(User, uid)
            barrier.wait(timeout=5)
            try:
                result = service.change_cutting_factory(db, oid, ProductionCuttingFactoryIn(cutting_department_code=target), user)
                return 200, result.changed
            except HTTPException as rejected:
                return rejected.status_code, False
    for round_index in range(10):
        target = "ECT" if round_index % 2 == 0 else "CUT"
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, target, barrier) for _ in range(2)]
            results = [future.result(timeout=12) for future in futures]
        assert all(code in {200, 409} for code, _ in results), results
        assert sum(changed for _, changed in results) == 1
        with sessions() as db:
            assert move(db, oid, uid, target).changed is False
    with sessions() as db:
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 10
        assert route_snapshot(db, oid)[0]["department_id"] == before[0]["department_id"]
        assert all(row["planned_input_qty"] == row["planned_output_qty"] == 120 for row in route_snapshot(db, oid))
        assert db.query(CuttingRecord).filter_by(work_order_id=works["cutting"]).count() == 0


def test_record_commit_wins_and_routing_retry_cannot_move_evidence(cutting_factory_postgres):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    with sessions() as recording, sessions() as routing:
        recording.query(ProductionOrder).filter_by(id=oid).with_for_update().one()
        recording.query(WorkOrder).filter_by(id=works["cutting"]).with_for_update().one()
        recording.add(CuttingRecord(work_order_id=works["cutting"], cut_pieces=1, passed_pieces=1)); recording.flush()
        with pytest.raises(HTTPException) as busy:
            move(routing, oid, uid)
        assert busy.value.status_code == 409
        recording.commit()
        with pytest.raises(HTTPException) as history:
            move(routing, oid, uid)
        assert history.value.detail == "CUTTING_FACTORY_HISTORY_LOCKED"
    with sessions() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(CuttingRecord).filter_by(work_order_id=works["cutting"]).count() == 1
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0


@pytest.mark.parametrize("writer", ["quality", "bundle"])
def test_stale_cached_cutting_scope_is_refreshed_before_other_evidence(cutting_factory_postgres, writer):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records", "cutting.bundles"])
        model_id = db.get(ProductionOrder, oid).model_id
    with sessions() as stale:
        cached = stale.get(WorkOrder, works["cutting"])
        assert cached.department_id == stale.query(Department.id).filter_by(code="CUT").scalar()
        actor = stale.get(User, uid)
        with sessions() as changing:
            assert move(changing, oid, uid).changed is True
        with pytest.raises(HTTPException) as rejected:
            if writer == "quality":
                production.post_quality(QualityCheckIn(work_order_id=cached.id, checked_qty=1, passed_qty=1, failed_qty=0), stale, actor)
            else:
                bundles.create_bundle_api(BundleIn(production_order_id=oid, model_id=model_id, color="white", size="S", quantity=1), stale, actor)
        assert rejected.value.status_code == 403
        stale.rollback()
    with sessions() as db:
        assert db.query(QualityCheck).filter_by(work_order_id=works["cutting"]).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=oid).count() == 0


def test_cutting_record_reauthorizes_after_competing_move(cutting_factory_postgres, monkeypatch):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records"])
    original = production.require_work_order_factory_access
    calls = []
    def after_initial_authorization(current, db, work):
        original(current, db, work)
        calls.append(work.department_id)
        if len(calls) == 1:
            with sessions() as changing:
                assert move(changing, oid, uid).changed is True
    monkeypatch.setattr(production, "require_work_order_factory_access", after_initial_authorization)
    # post_cutting imports the same helper locally, so patch the owning module too.
    from app.models import factory_scope_service
    monkeypatch.setattr(factory_scope_service, "require_work_order_factory_access", after_initial_authorization)
    with sessions() as stale:
        with pytest.raises(HTTPException) as rejected:
            production.post_cutting(CuttingRecordIn(work_order_id=works["cutting"], input_quantity=0,
                                                   cut_pieces=1, passed_pieces=1), stale, stale.get(User, uid))
        assert rejected.value.status_code == 403
        stale.rollback()
    with sessions() as db:
        assert db.query(CuttingRecord).filter_by(work_order_id=works["cutting"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 1


def test_fault_after_audit_queue_rolls_back_same_transaction(cutting_factory_postgres, monkeypatch):
    sessions, engine = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        before = route_snapshot(db, oid)
    original = service.log_action
    def queued_failure(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("queued-audit failure")
    monkeypatch.setattr(service, "log_action", queued_failure)
    with sessions() as db:
        with pytest.raises(RuntimeError, match="queued-audit failure"):
            move(db, oid, uid)
        assert not db.in_transaction()
    with sessions() as db:
        assert route_snapshot(db, oid) == before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0
        assert db.execute(text("SELECT current_setting('transaction_isolation')")).scalar() == "read committed"
