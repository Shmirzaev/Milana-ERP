"""Real PostgreSQL direct-label races, idempotency and failure recovery."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event, text
import pytest

from app.api.routes.package_workflows import create_packages_and_run
from app.libs.dto.fulfillment.package_workflows import PrintRunCreatePackagesIn
from app.models.packaging.package_sources_service import package_sources
from app.models.idempotency_service import bind_idempotency_identity
from app.models.factory_scope_service import bind_session_factory
from app.schemas import FinishedGoodsStock, Package, PackagePrintRun, PackagingRecord, Role, SewingRecord, User, WorkOrder
from app.tests.packaging_workflow_fixtures import seed_packaging_workflow
from app.tests.test_direct_packaging import body, package
from app.tests.test_package_write_postgres import package_write_postgres_sessions  # noqa: F401


def pg_actor(db, actor_id):
    actor = db.get(User, actor_id)
    bind_session_factory(actor, "MIL")
    bind_idempotency_identity(db, actor)
    return actor


def pg_seed(sessions):
    with sessions.begin() as db:
        role = Role(name=f"Direct-PG-{uuid4().hex}", permissions=["*"])
        actor = User(name="Direct PG", email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                     role=role, factory_code="MIL")
        db.add(actor); db.flush()
        facts = seed_packaging_workflow(db)["automatic"]
        row = db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).one()
        row.size_quantities = [{"size": "M", "quantity": 95}]
        return facts, actor.id


@pytest.mark.parametrize("same_key", [False, True])
def test_eight_direct_requests_conserve_passed_output_and_retry(package_write_postgres_sessions, same_key):
    sessions, _ = package_write_postgres_sessions
    facts, actor_id = pg_seed(sessions)
    common = body(facts)
    barrier = Barrier(8)

    def attempt(index):
        request = {**common, "request_key": common["request_key"] if same_key else str(uuid4())}
        barrier.wait(timeout=15)
        with sessions() as db:
            try:
                result = create_packages_and_run(PrintRunCreatePackagesIn.model_validate(request), db, pg_actor(db, actor_id))
                return "created", request, result
            except HTTPException as error:
                db.rollback()
                assert error.status_code == 400, error.detail
                return "refused", request, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    created = [row for row in outcomes if row[0] == "created"]
    assert len(created) == (8 if same_key else 1)
    assert all(row[2] == created[0][2] for row in created)
    with sessions() as db:
        work = db.get(WorkOrder, facts["work_order_id"])
        records = db.query(PackagingRecord).filter_by(work_order_id=work.id).all()
        packages = db.query(Package).filter_by(production_order_id=facts["order_id"]).all()
        assert len(records) == len(packages) == 1
        assert (records[0].input_qty, records[0].packed_qty) == (60, 60)
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty) == (60, 60, 60)
        assert work.status == "in_progress" and work.start_time is not None and work.end_time is None
        assert packages[0].total_quantity == 60 and packages[0].received_at is None
        assert db.query(FinishedGoodsStock).filter_by(package_id=packages[0].id).one().quantity == 60
        sources = package_sources(db, pg_actor(db, actor_id), work.id)
        assert sources.items[0].available_to_package == 35
    # A committed response can be recovered without repeating output/stock.
    with sessions() as db:
        request = PrintRunCreatePackagesIn.model_validate(created[0][1])
        assert create_packages_and_run(request, db, pg_actor(db, actor_id)) == created[0][2]
    with sessions() as db:
        assert db.query(PackagingRecord).filter_by(work_order_id=facts["work_order_id"]).count() == 1


def test_real_pg_failed_run_rolls_back_then_same_key_can_recover(package_write_postgres_sessions):
    sessions, _ = package_write_postgres_sessions
    facts, actor_id = pg_seed(sessions)
    request = body(facts, [package(facts, 30), package(facts, 65)])
    with sessions() as db:
        try:
            create_packages_and_run(PrintRunCreatePackagesIn.model_validate(request), db, pg_actor(db, actor_id))
        except HTTPException as error:
            assert error.status_code == 400
            db.rollback()
        else:
            pytest.fail("Over-capacity second package must refuse the whole transaction")
    with sessions() as db:
        assert db.query(PackagingRecord).filter_by(work_order_id=facts["work_order_id"]).count() == 0
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).count() == 0
        assert db.query(PackagePrintRun).filter_by(created_by=actor_id).count() == 0
        work = db.get(WorkOrder, facts["work_order_id"])
        assert work.actual_output_qty == 0
        assert work.status == "ready" and work.start_time is None and work.end_time is None
    request["packages"] = [package(facts, 60), package(facts, 35)]
    with sessions() as db:
        result = create_packages_and_run(PrintRunCreatePackagesIn.model_validate(request), db, pg_actor(db, actor_id))
        assert result["quantity"] == 95
    with sessions() as db:
        assert db.query(PackagingRecord).filter_by(work_order_id=facts["work_order_id"]).one().packed_qty == 95
        assert package_sources(db, pg_actor(db, actor_id), facts["work_order_id"]).items[0].available_to_package == 0


def test_sewing_defect_and_direct_labels_use_consistent_locks(package_write_postgres_sessions):
    from app.api.routes.production import post_sewing
    from app.libs.dto.production.production import SewingRecordIn
    from app.schemas import CuttingRecord, Department, WasteRecord
    sessions, engine = package_write_postgres_sessions
    facts, actor_id = pg_seed(sessions)
    with sessions.begin() as db:
        department = Department(code=f"CUT-{uuid4().hex[:8]}", name="Cutting race QA")
        db.add(department); db.flush()
        cut = WorkOrder(production_order_id=facts["order_id"], operation="cutting", department_id=department.id,
                        status="completed", passed_qty=97, actual_output_qty=97,
                        planned_input_qty=97, planned_output_qty=97)
        db.add(cut); db.flush()
        db.add(CuttingRecord(work_order_id=cut.id, production_batch_id=facts["batch_ids"][0],
                             input_quantity=0, input_unit="kg", cut_pieces=97, passed_pieces=97))
    first_locked, direct_attempt, direct_locked, release = Event(), Event(), Event(), Event()
    first_kind = []

    def before(connection, cursor, statement, parameters, context, many):
        sql = statement.strip().lower()
        if (connection.info.get("handoff_role") == "packaging" and "for update" in sql
                and sql.startswith("select production_orders.")):
            direct_attempt.set()

    def after(connection, cursor, statement, parameters, context, many):
        sql = statement.strip().lower()
        role = connection.info.get("handoff_role")
        if "for update" not in sql:
            return
        if role == "sewing" and not first_kind:
            first_kind.append("order" if sql.startswith("select production_orders.") else "work")
            first_locked.set()
            assert release.wait(10), "Controller must release the first Sewing lock"
        elif role == "packaging" and sql.startswith("select production_orders."):
            direct_locked.set()

    def sew():
        with sessions() as db:
            db.connection().info["handoff_role"] = "sewing"
            db.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
            return post_sewing(SewingRecordIn(work_order_id=facts["sewing_work_order_id"],
                production_batch_id=facts["batch_ids"][0], input_qty=2, sewn_qty=2,
                passed_qty=1, failed_qty=1, size_quantities=[{"size": "M", "quantity": 1}]),
                db, pg_actor(db, actor_id), None)

    def pack():
        with sessions() as db:
            db.connection().info["handoff_role"] = "packaging"
            db.execute(text("SET LOCAL deadlock_timeout = '100ms'"))
            return create_packages_and_run(PrintRunCreatePackagesIn.model_validate(body(facts)), db, pg_actor(db, actor_id))

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            sewing = pool.submit(sew)
            assert first_locked.wait(10), "Sewing must acquire its first production lock"
            packaging = pool.submit(pack)
            assert direct_attempt.wait(10)
            if first_kind == ["work"]:
                # This branch makes the historical WO->PO inversion reproducible:
                # allow Packaging to hold PO before Sewing inserts defect waste.
                assert direct_locked.wait(10)
            release.set()
            assert sewing.result(timeout=20)["id"] > 0
            assert packaging.result(timeout=20)["quantity"] == 60
        assert first_kind == ["order"]
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    with sessions() as db:
        records = db.query(SewingRecord).filter_by(work_order_id=facts["sewing_work_order_id"]).all()
        assert sum(row.passed_qty for row in records) == 96
        assert db.query(WasteRecord).filter_by(production_order_id=facts["order_id"], waste_type="sewing_defect").one().quantity == 1
        assert db.query(PackagingRecord).filter_by(work_order_id=facts["work_order_id"]).one().packed_qty == 60
        assert package_sources(db, pg_actor(db, actor_id), facts["work_order_id"]).items[0].available_to_package == 36
