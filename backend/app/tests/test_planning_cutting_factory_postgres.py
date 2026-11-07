"""Real PostgreSQL locks, stale-source writers, bounded races and recovery.

Only an explicitly configured loopback disposable database is accepted. This
fixture creates ORM tables in a unique synthetic schema; no Alembic runs.
"""
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes import bundles, cutting_passports, production
from app.db.base import Base
from app.libs.dto.planning.production_cutting_factory import ProductionCuttingFactoryIn
from app.libs.dto.production.cutting_passport import CuttingPassportIn
from app.libs.dto.production.production import CuttingRecordIn, QualityCheckIn, WorkOrderUpdate
from app.libs.dto.packaging.tracking import BundleIn
from app.models.planning import cutting_factory_service as service
from app.schemas import (
    AuditLog, Bundle, CuttingPassport, CuttingRecord, Department, Item, LegacyStockReceipt, Package,
    PayrollQrLabel, ProductionBatch, ProductionOrder, ProductionOrderMaterial, QualityCheck,
    SewingAssignment, SewingDailyReport, SewingFlow, StockBatch, User, Warehouse, WasteRecord, WorkOrder,
)
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


def test_material_replacement_rechecks_factory_after_initial_authorization(cutting_factory_postgres, monkeypatch):
    from app.models import cutting_material_assignment_service as material_service
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records"])
        marker = uuid4().hex[:12]
        item = Item(sku=f"QA-{marker}", name="Routing material", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"QA-{marker}", type="fabric_storage")
        db.add_all([item, warehouse]); db.flush()
        batches = [StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no=f"{marker}-{index}", quantity=100, unit="kg", qc_status="passed") for index in (1, 2)]
        db.add_all(batches); db.flush()
        material = ProductionOrderMaterial(production_order_id=oid, stock_batch_id=batches[0].id, estimated_quantity=10, unit="kg", position=1)
        db.add(material); db.commit()
        old_id, new_id, material_id = batches[0].id, batches[1].id, material.id
    original = material_service.require_work_order_factory_access
    calls = []
    def initial_then_move(current, db, work):
        original(current, db, work)
        calls.append(work.department_id)
        if len(calls) == 1:
            with sessions() as changing:
                assert move(changing, oid, uid).changed is True
    monkeypatch.setattr(material_service, "require_work_order_factory_access", initial_then_move)
    with sessions() as stale:
        with pytest.raises(HTTPException) as rejected:
            material_service.replace_cutting_material_batch(stale, stale.get(User, uid), works["cutting"], old_id, new_id)
        assert rejected.value.status_code == 403
        stale.rollback()
    with sessions() as db:
        assert db.get(ProductionOrderMaterial, material_id).stock_batch_id == old_id
        assert db.query(AuditLog).filter_by(entity_id=oid, action="correct_cutting_material_batch").count() == 0
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 1


def test_passport_creation_refreshes_previously_authorized_identity(cutting_factory_postgres, monkeypatch):
    from app.models import factory_scope_service
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records"])
    original = factory_scope_service.require_work_order_factory_access
    calls = []
    def initial_then_move(current, db, work):
        original(current, db, work)
        calls.append(work.department_id)
        if len(calls) == 1:
            with sessions() as changing:
                assert move(changing, oid, uid).changed is True
    monkeypatch.setattr(factory_scope_service, "require_work_order_factory_access", initial_then_move)
    monkeypatch.setattr(cutting_passports, "require_work_order_factory_access", initial_then_move)
    with sessions() as stale:
        with pytest.raises(HTTPException) as rejected:
            cutting_passports.create_passport(CuttingPassportIn(production_order_id=oid, passport_no=uuid4().hex,
                date=datetime.now(timezone.utc)), stale, stale.get(User, uid))
        assert rejected.value.status_code == 403
        stale.rollback()
    with sessions() as db:
        assert db.query(CuttingPassport).filter_by(production_order_id=oid).count() == 0
        assert db.query(ProductionBatch).filter_by(production_order_id=oid).count() == 1


@pytest.mark.parametrize("writer", ["update", "start", "split", "extra"])
def test_cutting_commands_and_batch_creates_refresh_stale_factory_scope(cutting_factory_postgres, writer):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db, permissions=["planning.production", "cutting.records"])
    with sessions() as stale:
        cached = stale.get(WorkOrder, works["cutting"])
        actor = stale.get(User, uid)
        with sessions() as changing:
            assert move(changing, oid, uid).changed is True
            after_move = route_snapshot(changing, oid)
        with pytest.raises(HTTPException) as rejected:
            if writer == "update":
                production.update_wo(cached.id, WorkOrderUpdate(notes="must not follow routing"), stale, actor)
            elif writer == "start":
                production.start_wo(cached.id, stale, actor)
            elif writer == "split":
                production.split_cutting_work_order_batches(cached.id, production.SplitWorkOrderBatchesIn(batches=[{"planned_quantity": 120}]), stale, actor)
            else:
                production.add_extra_cutting_batch(cached.id, production.ExtraCuttingBatchIn(planned_quantity=1), stale, actor)
        assert rejected.value.status_code == 403
        stale.rollback()
    with sessions() as db:
        assert route_snapshot(db, oid) == after_move
        assert db.query(ProductionBatch).filter_by(production_order_id=oid).count() == 1
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 1


@pytest.mark.parametrize("kind", ["work_waste", "batch_payroll", "assignment_report", "batch_package"])
def test_optional_order_reference_evidence_is_guarded_on_postgres(cutting_factory_postgres, kind):
    sessions, _ = cutting_factory_postgres
    with sessions() as db:
        oid, uid, works = make_order(db)
        batch = db.query(ProductionBatch).filter_by(production_order_id=oid).one()
        marker = uuid4().hex
        if kind == "work_waste":
            evidence = WasteRecord(work_order_id=works["cutting"], waste_type="cutting_waste", quantity=1, unit="kg")
        elif kind == "batch_payroll":
            evidence = PayrollQrLabel(production_batch_id=batch.id, label_uid=marker, quantity=1)
        elif kind == "assignment_report":
            flow = SewingFlow(code=marker[:20], name=f"QA {marker}", factory_code="MIL")
            db.add(flow); db.flush()
            assignment = SewingAssignment(work_order_id=works["sewing"], sewing_flow_id=flow.id, quantity=120, status="planned")
            db.add(assignment); db.flush()
            evidence = SewingDailyReport(sewing_assignment_id=assignment.id, sewing_flow_id=flow.id,
                report_date=datetime(2026, 11, 4).date(), line_code=flow.code, line_name=flow.name, sewn_qty=1)
        else:
            receipt = LegacyStockReceipt(source_system="QA", source_warehouse_id="QA", source_record_id=marker,
                                         source_checksum=marker, source_payload={})
            db.add(receipt); db.flush()
            evidence = Package(production_batch_id=batch.id, legacy_receipt_id=receipt.id, package_no=marker,
                               barcode=marker, color="white", total_quantity=1, capacity=60)
        db.add(evidence); db.commit(); db.expire_all()
        assert evidence.production_order_id is None
        before = route_snapshot(db, oid)
        row_before = {column.name: getattr(evidence, column.name) for column in evidence.__table__.columns}
        row_type, row_id = type(evidence), evidence.id
        assert service.cutting_factory_options(db, oid, db.get(User, uid)).can_change is False
        with pytest.raises(HTTPException) as rejected:
            move(db, oid, uid)
        assert rejected.value.status_code == 409
    with sessions() as db:
        assert route_snapshot(db, oid) == before
        stored = db.get(row_type, row_id)
        assert {column.name: getattr(stored, column.name) for column in stored.__table__.columns} == row_before
        assert db.query(AuditLog).filter_by(entity_id=oid, action="change_cutting_factory").count() == 0
