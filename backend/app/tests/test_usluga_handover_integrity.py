"""Usluga handover and edits serialize without reversing package lock order."""

import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.routes.usluga import (
    UslugaHandoverIn,
    UslugaMaterialIn,
    hand_over_usluga_order,
    update_usluga_material,
)
from app.db.base import Base
from app.models import (
    AuditLog,
    Department,
    Model,
    Package,
    PackageScanLog,
    ProductionOrder,
    User,
    WorkOrder,
)
from app.tests.conftest import TestSessionLocal


def _case(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        model = Model(
            code=f"WF11-{marker}",
            name="WF11 synthetic Usluga model",
            catalog_scope="usluga",
            factory_code="ECO",
        )
        actor = User(
            name="WF11 Eco operator",
            email=f"wf11-{marker}@example.invalid",
            password_hash="unused",
            factory_code="ECO",
            extra_permissions=["usluga.manage", "usluga.handover"],
        )
        db.add_all([model, actor])
        departments = [
            Department(name=f"WF11 {operation} {marker}", code=f"{operation[:1].upper()}{marker[:7]}{index}")
            for index, operation in enumerate(("cutting", "sewing", "packaging"))
        ]
        db.add_all(departments)
        db.flush()
        order = ProductionOrder(
            production_no=f"USL-WF11-{marker}",
            production_type="service_order",
            source_type="usluga",
            model_id=model.id,
            status="ready_for_handover",
            planned_quantity=10,
            service_customer_name="Synthetic outside customer",
            service_material_usage_kg=5,
        )
        db.add(order)
        db.flush()
        for department, operation in zip(departments, ("cutting", "sewing", "packaging"), strict=True):
            db.add(WorkOrder(
                production_order_id=order.id,
                department_id=department.id,
                operation=operation,
                status="completed",
                planned_input_qty=10,
                planned_output_qty=10,
                actual_input_qty=10,
                actual_output_qty=10,
                passed_qty=10,
            ))
        package = Package(
            package_no=f"WF11-PKG-{marker}",
            barcode=f"WF11-BC-{marker}",
            packaging_department_code="ECP",
            production_order_id=order.id,
            model_id=model.id,
            color="Natural",
            total_quantity=10,
            capacity=60,
            status="packed",
        )
        db.add(package)
        db.flush()
        return {
            "actor_id": actor.id,
            "model_id": model.id,
            "order_id": order.id,
            "package_id": package.id,
            "marker": marker,
        }


def _handover_with_db(db, case, recipient):
    try:
        result = hand_over_usluga_order(
            case["order_id"],
            UslugaHandoverIn(recipient=recipient),
            db,
            db.get(User, case["actor_id"]),
        )
        return 200, result["handover_recipient"]
    except HTTPException as rejected:
        db.rollback()
        return rejected.status_code, None


def _handover(sessions, case, recipient):
    with sessions() as db:
        return _handover_with_db(db, case, recipient)


def _material(sessions, case, usage):
    with sessions() as db:
        try:
            result = update_usluga_material(
                case["order_id"],
                UslugaMaterialIn(
                    material_usage_kg=usage,
                    material_description="Synthetic customer material",
                    material_notes="WF11 concurrency proof",
                ),
                db,
                db.get(User, case["actor_id"]),
            )
            return 200, result["material_usage_kg"]
        except HTTPException as rejected:
            db.rollback()
            return rejected.status_code, None


def test_handover_is_single_use_and_freezes_material_edits():
    case = _case(TestSessionLocal)
    assert _handover(TestSessionLocal, case, "First recipient")[0] == 200
    assert _handover(TestSessionLocal, case, "Second recipient")[0] == 409
    assert _material(TestSessionLocal, case, 9)[0] == 409

    with TestSessionLocal() as db:
        order = db.get(ProductionOrder, case["order_id"])
        assert order.service_handover_recipient == "First recipient"
        assert float(order.service_material_usage_kg) == 5
        assert db.query(PackageScanLog).filter_by(
            package_id=case["package_id"],
            scan_type="usluga_handover",
        ).count() == 1
        assert db.query(AuditLog).filter_by(action="handover", entity_id=case["order_id"]).count() == 1
        assert db.query(AuditLog).filter_by(action="update_material", entity_id=case["order_id"]).count() == 0


@pytest.fixture(scope="module")
def usluga_postgres_sessions():
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Requires disposable PostgreSQL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Only loopback PostgreSQL without overrides is supported")
    schema = f"usluga_handover_{uuid4().hex}"
    engine = create_engine(
        url,
        pool_size=6,
        max_overflow=0,
        connect_args={
            "options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000",
        },
    )
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _wait_until_blocked(observer, pids):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        blocked = [
            bool(observer.execute(text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}).scalar_one())
            for pid in pids
        ]
        if all(blocked):
            return
        sleep(0.02)
    pytest.fail("Expected Usluga writer(s) to visibly wait on PostgreSQL row locks")


def test_postgres_concurrent_handovers_create_one_release(usluga_postgres_sessions):
    sessions = usluga_postgres_sessions
    case = _case(sessions)
    ready = Queue()

    def handover(recipient):
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return _handover_with_db(db, case, recipient)

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.query(Package).filter(Package.id == case["package_id"]).with_for_update(of=Package).one()
        futures = [workers.submit(handover, recipient) for recipient in ("Recipient A", "Recipient B")]
        pids = [ready.get(timeout=10) for _ in futures]
        try:
            _wait_until_blocked(holder, pids)
        finally:
            holder.rollback()
        results = [future.result(timeout=20) for future in futures]

    assert sorted(status for status, _ in results) == [200, 409]
    winner = next(recipient for status, recipient in results if status == 200)
    with sessions() as db:
        assert db.get(ProductionOrder, case["order_id"]).service_handover_recipient == winner
        assert db.query(PackageScanLog).filter_by(
            package_id=case["package_id"],
            scan_type="usluga_handover",
        ).count() == 1


def test_postgres_package_lock_does_not_block_material_before_handover(usluga_postgres_sessions):
    sessions = usluga_postgres_sessions
    case = _case(sessions)
    ready = Queue()

    def handover():
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return _handover_with_db(db, case, "Serialized recipient")

    with sessions() as holder, ThreadPoolExecutor(max_workers=2) as workers:
        holder.query(Package).filter(Package.id == case["package_id"]).with_for_update(of=Package).one()
        handover_future = workers.submit(handover)
        _wait_until_blocked(holder, [ready.get(timeout=10)])
        material_future = workers.submit(_material, sessions, case, 7)
        deadline = monotonic() + 5
        while monotonic() < deadline and not material_future.done():
            sleep(0.02)
        material_completed_before_package_release = material_future.done()
        holder.rollback()
        material_result = material_future.result(timeout=20)
        handover_result = handover_future.result(timeout=20)

    assert material_completed_before_package_release
    assert material_result == (200, 7.0)
    assert handover_result == (200, "Serialized recipient")
    with sessions() as db:
        order = db.get(ProductionOrder, case["order_id"])
        assert float(order.service_material_usage_kg) == 7
        assert order.handed_over_at is not None
        audit_actions = [
            row.action
            for row in db.query(AuditLog)
            .filter(AuditLog.entity_type == "UslugaOrder", AuditLog.entity_id == case["order_id"])
            .order_by(AuditLog.id)
            .all()
        ]
        assert audit_actions == ["update_material", "handover"]


def test_postgres_handover_rejects_package_membership_change(usluga_postgres_sessions):
    sessions = usluga_postgres_sessions
    case = _case(sessions)
    ready = Queue()

    def handover():
        with sessions() as db:
            ready.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            return _handover_with_db(db, case, "Stale package snapshot")

    with sessions() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder.query(ProductionOrder).filter(
            ProductionOrder.id == case["order_id"],
        ).with_for_update(of=ProductionOrder).one()
        future = workers.submit(handover)
        pid = ready.get(timeout=10)
        _wait_until_blocked(holder, [pid])
        holder.add(Package(
            package_no=f"WF11-NEW-{case['marker']}",
            barcode=f"WF11-NEW-BC-{case['marker']}",
            packaging_department_code="ECP",
            production_order_id=case["order_id"],
            model_id=case["model_id"],
            color="Natural",
            total_quantity=1,
            capacity=60,
            status="packed",
        ))
        holder.commit()
        result = future.result(timeout=20)

    assert result[0] == 409
    with sessions() as db:
        assert db.get(ProductionOrder, case["order_id"]).handed_over_at is None
        assert db.query(Package).filter_by(production_order_id=case["order_id"], status="packed").count() == 2
        assert (
            db.query(PackageScanLog)
            .join(Package, Package.id == PackageScanLog.package_id)
            .filter(
                Package.production_order_id == case["order_id"],
                PackageScanLog.scan_type == "usluga_handover",
            )
            .count()
            == 0
        )
