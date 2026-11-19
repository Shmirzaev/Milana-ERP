"""Force legacy Sewing entry points to overlap real direct Packaging on PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import text

from app.api.routes.bundles import api_receive_sewing
from app.api.routes.package_workflows import create_packages_and_run, record_packaging_damage
from app.api.routes.production import PackagingReceiveFromSewingIn, post_printing, receive_packaging_from_sewing
from app.api.routes.sewing_bands import ReceiveIn, receive, record_output
from app.api.routes.sewing_corrections import Correction, DeleteInput, delete, update
from app.libs.dto.fulfillment.package_workflows import PrintRunCreatePackagesIn
from app.libs.dto.packaging.packaging_damage_input import PackagingDamageIn
from app.libs.dto.production.production import PrintingRecordIn, SewingRecordIn
from app.libs.dto.production.sewing_manual_receive import SewingManualReceiveIn
from app.models.factory_scope_service import bind_session_factory
from app.models.idempotency_service import bind_idempotency_identity
from app.models.production.sewing_receipt_service import accept_sewing_batch, receive_manual_sewing
from app.schemas import (
    Bundle, CuttingRecord, Department, Package, PackagingReceipt, PackagingRecord, PrintingRecord, ProductionOrder,
    SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder,
)
from app.tests.test_direct_packaging import body
from app.tests.test_direct_packaging_postgres import pg_seed
from app.tests.test_package_write_postgres import package_write_postgres_sessions  # noqa: F401


def _actor(db, actor_id):
    actor = db.get(User, actor_id)
    bind_session_factory(actor, "ECO")
    bind_idempotency_identity(db, actor)
    return actor


def _seed(sessions, operation):
    facts, actor_id = pg_seed(sessions)
    with sessions.begin() as db:
        departments = {}
        for code in ("ECO", "ECP", "ECT"):
            row = db.query(Department).filter_by(code=code).first()
            if row is None:
                row = Department(code=code, name=f"Lock QA {code}")
                db.add(row); db.flush()
            departments[code] = row.id
        marker = uuid4().hex[:12]
        flow = SewingFlow(code=f"LOCK-{marker}", name=f"Lock QA {marker}", factory_code="ECO", is_active=True)
        db.add(flow); db.flush()
        actor = db.get(User, actor_id)
        actor.factory_code = "ECO"
        band = User(name="Lock QA band", email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                    role_id=actor.role_id, factory_code="ECO", sewing_band_id=flow.id)
        db.add(band); db.flush()
        work = db.get(WorkOrder, facts["sewing_work_order_id"])
        work.department_id = departments["ECO"]
        work.status = "completed" if operation == "scanner" else "in_progress"
        work.planned_input_qty = work.planned_output_qty = 97
        db.get(WorkOrder, facts["work_order_id"]).department_id = departments["ECP"]
        cut = WorkOrder(production_order_id=facts["order_id"], department_id=departments["ECT"],
                        operation="cutting", status="completed", planned_input_qty=97, planned_output_qty=97,
                        actual_input_qty=97, actual_output_qty=97, passed_qty=97)
        db.add(cut); db.flush()
        db.add(CuttingRecord(work_order_id=cut.id, production_batch_id=facts["batch_ids"][0],
                             input_quantity=0, input_unit="kg", cut_pieces=97, passed_pieces=97))
        bundles = []
        for quantity, status in ((96, "received_sewing"), (1, "created")):
            token = uuid4().hex
            bundle = Bundle(bundle_no=token, barcode=token, production_order_id=facts["order_id"],
                            production_batch_id=facts["batch_ids"][0], model_id=facts["model_id"],
                            color="white", size="M", quantity=quantity, status=status,
                            sewing_factory_code="ECO", next_department_id=departments["ECO"])
            db.add(bundle); bundles.append(bundle)
        db.flush()
        facts.update(actor_id=actor_id, band_id=band.id, flow_id=flow.id, bundle_id=bundles[1].id)
        facts["record_id"] = db.query(SewingRecord.id).filter_by(work_order_id=work.id).scalar()
        if operation in ("band_output", "band_receive"):
            work.sewing_flow_id = flow.id
            assignment = SewingAssignment(work_order_id=work.id, production_batch_id=facts["batch_ids"][0],
                                          sewing_flow_id=flow.id, quantity=97, completed_qty=95,
                                          status="in_progress", created_by=actor_id)
            db.add(assignment); db.flush()
            facts["assignment_id"] = assignment.id
        if operation == "printing":
            from app.models.inventory_service import ACCESSORY_SEWING_BLOCK_REASON
            printing_department = db.query(Department).filter_by(code="PRT").first()
            if printing_department is None:
                printing_department = Department(code="PRT", name="Printing")
                db.add(printing_department); db.flush()
            printer = User(name="Printing lock QA", email=f"{uuid4().hex}@example.invalid", password_hash="unused",
                           role_id=actor.role_id, factory_code="MIL")
            printing = WorkOrder(production_order_id=facts["order_id"], department_id=printing_department.id,
                                 operation="printing", status="in_progress", planned_input_qty=97, planned_output_qty=97,
                                 actual_input_qty=96, actual_output_qty=96, passed_qty=96)
            db.add_all([printer, printing]); db.flush()
            db.add(PrintingRecord(work_order_id=printing.id, production_batch_id=facts["batch_ids"][0],
                                  input_qty=96, printed_qty=96, passed_qty=96, rejected_qty=0))
            work.is_blocked = True
            work.block_reason = ACCESSORY_SEWING_BLOCK_REASON
            db.get(ProductionOrder, facts["order_id"]).status = "printing"
            facts.update(printing_work_order_id=printing.id, printing_actor_id=printer.id)
    return facts


def _legacy(db, facts, operation):
    if operation == "printing":
        printer = db.get(User, facts["printing_actor_id"])
        bind_session_factory(printer, "MIL")
        return post_printing(PrintingRecordIn(work_order_id=facts["printing_work_order_id"],
            production_batch_id=facts["batch_ids"][0], input_qty=1, printed_qty=1, passed_qty=1), db, printer)
    actor = _actor(db, facts["band_id"] if operation.startswith("band_") else facts["actor_id"])
    if operation == "packaging_receipt":
        return receive_packaging_from_sewing(PackagingReceiveFromSewingIn(
            work_order_id=facts["work_order_id"], production_batch_id=facts["batch_ids"][0],
            quantity=95, packaging_department_code="ECP"), db, actor)
    if operation == "band_output":
        return record_output(facts["assignment_id"], SewingRecordIn(work_order_id=facts["sewing_work_order_id"],
            production_batch_id=facts["batch_ids"][0], sewing_assignment_id=facts["assignment_id"],
            input_qty=0, sewn_qty=1, passed_qty=1, size_quantities=[{"size": "M", "quantity": 1}]), db, actor, None)
    if operation == "band_receive":
        return receive(ReceiveIn(production_order_id=facts["order_id"], production_batch_id=facts["batch_ids"][0]), db, actor)
    if operation in ("manual", "manual_flow"):
        return receive_manual_sewing(db, SewingManualReceiveIn(production_order_id=facts["order_id"],
            production_batch_id=facts["batch_ids"][0], factory_code="ECO",
            sewing_flow_id=facts["flow_id"] if operation == "manual_flow" else None), actor)
    if operation == "batch":
        return accept_sewing_batch(db, facts["batch_ids"][0], facts["flow_id"], actor)
    if operation == "scanner":
        return api_receive_sewing(facts["bundle_id"], db, actor)
    if operation == "correction_update":
        return update(facts["record_id"], Correction(expected_version=0, input_qty=95, sewn_qty=95,
            passed_qty=95, size_quantities=[{"size": "M", "quantity": 95}]), db, actor)
    assert operation == "correction_delete"
    return delete(facts["record_id"], DeleteInput(expected_version=0), db, actor)


def _direct(db, facts, action):
    actor = _actor(db, facts["actor_id"])
    if action == "labels":
        return create_packages_and_run(PrintRunCreatePackagesIn.model_validate(body(facts)), db, actor)
    return record_packaging_damage(PackagingDamageIn(request_key=uuid4(), work_order_id=facts["work_order_id"],
        production_batch_id=facts["batch_ids"][0], damaged_qty=1), db, actor)


@pytest.mark.parametrize("operation", ["packaging_receipt", "band_output", "band_receive", "manual", "manual_flow",
                                       "batch", "scanner", "correction_update", "correction_delete", "printing"])
@pytest.mark.parametrize("action", ["labels", "damage"])
def test_legacy_writer_waits_before_source_locks_then_direct_output_conserves(
        package_write_postgres_sessions, operation, action):
    sessions, _ = package_write_postgres_sessions
    facts = _seed(sessions, operation)
    worker_pid = Queue()

    def legacy():
        with sessions() as db:
            worker_pid.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            try:
                result = _legacy(db, facts, operation)
                db.commit()
                return result
            except HTTPException as error:
                db.rollback()
                assert operation.startswith("correction_")
                assert (error.status_code, error.detail) == (409, "sewingEdit.handedOff")
                return "handed-off refusal"

    with sessions() as holder, ThreadPoolExecutor(max_workers=1) as workers:
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        holder.execute(text("SELECT id FROM production_orders WHERE id=:id FOR UPDATE"), {"id": facts["order_id"]})
        future = workers.submit(legacy)
        pid = worker_pid.get(timeout=10)
        try:
            deadline = monotonic() + 10
            while monotonic() < deadline:
                holder.execute(text("SELECT pg_stat_clear_snapshot()"))
                blocked = holder.execute(text("SELECT query FROM pg_stat_activity WHERE pid=:pid "
                    "AND :holder = ANY(pg_blocking_pids(pid))"), {"pid": pid, "holder": holder_pid}).scalar()
                if blocked:
                    assert blocked.lstrip().lower().startswith("select production_orders.")
                    assert "FOR UPDATE" in blocked
                    break
                if future.done():
                    future.result()
                    pytest.fail("Legacy writer completed without serializing on the parent order")
                sleep(0.02)
            else:
                pytest.fail("Legacy writer did not visibly wait for the locked parent")
            # Historical wrappers retained this WO while waiting for the parent,
            # deadlocking direct Packaging. NOWAIT makes that regression decisive.
            holder.execute(text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE NOWAIT"),
                           {"id": facts["sewing_work_order_id"]}).scalar_one()
            if operation == "printing":
                holder.execute(text("SELECT id FROM work_orders WHERE id=:id FOR UPDATE NOWAIT"),
                               {"id": facts["printing_work_order_id"]}).scalar_one()
            holder.execute(text("SELECT id FROM production_batches WHERE id=:id FOR UPDATE NOWAIT"),
                           {"id": facts["batch_ids"][0]}).scalar_one()
            holder.execute(text("SELECT id FROM bundles WHERE id=:id FOR UPDATE NOWAIT"),
                           {"id": facts["bundle_id"]}).scalar_one()
            _direct(holder, facts, action)
        finally:
            holder.rollback()
        future.result(timeout=20)

    with sessions() as db:
        rows = db.query(PackagingRecord).filter_by(work_order_id=facts["work_order_id"]).all()
        assert len(rows) == 1
        assert (sum(row.input_qty for row in rows), sum(row.packed_qty for row in rows),
                sum(row.damaged_qty for row in rows)) == ((60, 60, 0) if action == "labels" else (1, 0, 1))
        work = db.get(WorkOrder, facts["work_order_id"])
        assert work.actual_input_qty == (60 if action == "labels" else 1)
        assert db.query(Package).filter_by(production_order_id=facts["order_id"]).count() == (action == "labels")
        if operation == "packaging_receipt":
            assert db.query(PackagingReceipt).filter_by(work_order_id=work.id).one().quantity == 95
        elif operation in ("band_receive", "manual", "manual_flow", "batch", "scanner"):
            assert db.get(Bundle, facts["bundle_id"]).status == "received_sewing"
            assert db.get(WorkOrder, facts["sewing_work_order_id"]).actual_input_qty == 97
            if operation in ("manual_flow", "batch"):
                assignment = db.query(SewingAssignment).filter_by(work_order_id=facts["sewing_work_order_id"]).one()
                assert assignment.quantity == 97
        elif operation == "band_output":
            assert db.get(SewingAssignment, facts["assignment_id"]).completed_qty == 96
        elif operation == "printing":
            printing = db.get(WorkOrder, facts["printing_work_order_id"])
            assert (printing.actual_input_qty, printing.actual_output_qty, printing.passed_qty) == (97, 97, 97)
            assert db.query(PrintingRecord).filter_by(work_order_id=printing.id).count() == 2
            assert not db.get(WorkOrder, facts["sewing_work_order_id"]).is_blocked
        assert sum(row.passed_qty for row in db.query(SewingRecord).filter_by(
            work_order_id=facts["sewing_work_order_id"])) == (96 if operation == "band_output" else 95)


@pytest.mark.parametrize("receipt_first", [False, True])
def test_physical_receipt_and_direct_record_do_not_double_input(package_write_postgres_sessions, receipt_first):
    sessions, _ = package_write_postgres_sessions
    facts = _seed(sessions, "packaging_receipt")
    for operation in (("receipt", "labels") if receipt_first else ("labels", "receipt")):
        with sessions() as db:
            _legacy(db, facts, "packaging_receipt") if operation == "receipt" else _direct(db, facts, "labels")
    with sessions() as db:
        assert db.get(WorkOrder, facts["work_order_id"]).actual_input_qty == 60
        assert db.query(PackagingReceipt).filter_by(work_order_id=facts["work_order_id"]).one().quantity == 95


def test_explicit_zero_record_remains_zero_after_physical_receipt(package_write_postgres_sessions):
    sessions, _ = package_write_postgres_sessions
    facts = _seed(sessions, "packaging_receipt")
    with sessions.begin() as db:
        db.add(PackagingRecord(work_order_id=facts["work_order_id"], production_batch_id=facts["batch_ids"][0],
                               input_qty=0, packed_qty=0))
    with sessions() as db:
        _legacy(db, facts, "packaging_receipt")
    with sessions() as db:
        assert db.get(WorkOrder, facts["work_order_id"]).actual_input_qty == 0
