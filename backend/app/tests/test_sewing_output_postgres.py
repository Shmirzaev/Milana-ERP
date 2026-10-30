"""Approved PostgreSQL coverage for the complete shared Sewing output transaction."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.api.routes.production import post_sewing
from app.libs.dto.production.production import SewingRecordIn
from app.models.idempotency_service import bind_idempotency_identity
from app.schemas import (
    AuditLog, Bundle, Department, IdempotencyRecord, Item, ManualAccessoryIssue, Model, ModelBOM, Notification,
    ProductionOrder, SewingAssignment, SewingFlow, SewingRecord, StockMovement, User,
    WasteRecord, WorkOrder,
)
from app.tests.test_customer_create_postgres import chain, customer_pg_sessions  # noqa: F401


@pytest.fixture
def sewing_case(customer_pg_sessions):
    marker = uuid4().hex[:12]
    with customer_pg_sessions.begin() as db:
        def department(code: str) -> Department:
            row = db.query(Department).filter_by(code=code).first()
            if row is None:
                row = Department(code=code, name=f"Sewing QA {code}")
                db.add(row)
                db.flush()
            return row

        cut_dept, sew_dept = department("ECT"), department("ECO")
        package_dept, legacy_package_dept = department("ECP"), department("PKG")
        actor = User(
            name="Sewing QA", email=f"sewing-{marker}@example.invalid", password_hash="unused",
            factory_code="ECO", department_id=sew_dept.id, extra_permissions=["*"], is_active=True,
        )
        package_user = User(
            name="Packaging QA", email=f"package-{marker}@example.invalid", password_hash="unused",
            factory_code="ECO", department_id=package_dept.id, extra_permissions=["*"], is_active=True,
        )
        model = Model(code=f"SEW-{marker}", name=f"Sewing QA {marker}", factory_code="ECO")
        flow = SewingFlow(code=f"QA-{marker}", name=f"QA line {marker}", factory_code="ECO", is_active=True)
        db.add_all([actor, package_user, model, flow])
        db.flush()
        order = ProductionOrder(
            production_no=f"SEW-QA-{marker}", model_id=model.id,
            production_type="branded_stock", planned_quantity=50, status="sewing",
        )
        db.add(order)
        db.flush()
        cutting = WorkOrder(
            production_order_id=order.id, department_id=cut_dept.id, operation="cutting",
            status="completed", planned_input_qty=50, planned_output_qty=50,
            actual_input_qty=50, actual_output_qty=50, passed_qty=50,
        )
        sewing = WorkOrder(
            production_order_id=order.id, department_id=sew_dept.id, operation="sewing",
            status="in_progress", planned_input_qty=50, planned_output_qty=5,
        )
        packaging = WorkOrder(
            production_order_id=order.id, department_id=legacy_package_dept.id, operation="packaging",
            status="waiting", planned_input_qty=50, planned_output_qty=50,
        )
        db.add_all([cutting, sewing, packaging])
        db.flush()
        bundle = Bundle(
            bundle_no=f"SEW-{marker}", barcode=f"SEW-{marker}", production_order_id=order.id,
            model_id=model.id, color="white", size="M", quantity=50,
            sewing_factory_code="ECO", current_department_id=cut_dept.id,
            next_department_id=sew_dept.id, status="created",
        )
        assignment = SewingAssignment(
            work_order_id=sewing.id, production_batch_id=None, sewing_flow_id=flow.id,
            quantity=20, completed_qty=0, status="planned",
        )
        db.add_all([bundle, assignment])
        db.flush()
        # Keep the created bundle for the factory path; the band test marks the
        # same fixture's bundle received in its own isolated invocation.
        return {
            "actor_id": actor.id, "package_user_id": package_user.id, "order_id": order.id,
            "cutting_id": cutting.id, "sewing_id": sewing.id, "packaging_id": packaging.id,
            "bundle_id": bundle.id, "assignment_id": assignment.id, "flow_id": flow.id,
        }


def _payload(case, *, passed=8, failed=2, input_qty=10, sewn_qty=10):
    return SewingRecordIn(
        work_order_id=case["sewing_id"], sewing_assignment_id=case["assignment_id"],
        input_qty=input_qty, sewn_qty=sewn_qty, passed_qty=passed, failed_qty=failed,
    )


def test_pg_factory_output_persists_all_participants_and_replays_once(customer_pg_sessions, sewing_case):
    case = sewing_case
    key = "sewing-replay-" + uuid4().hex
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, actor)
        payload = _payload(case, passed=6, failed=1, input_qty=7, sewn_qty=7)
        commits = []

        def count_commit(session):
            if session is db:
                commits.append(1)

        event.listen(Session, "after_commit", count_commit)
        try:
            first = post_sewing(payload, db, actor, key)
            replay = post_sewing(payload, db, actor, key)
            with pytest.raises(HTTPException) as mismatch:
                post_sewing(_payload(case, passed=5, failed=2, input_qty=7, sewn_qty=7), db, actor, key)
            assert mismatch.value.status_code == 409
            db.rollback()
        finally:
            event.remove(Session, "after_commit", count_commit)
        assert replay == first
        assert len(commits) == 1, "the complete output operation must commit exactly once; replay/refusal must not commit"
    with customer_pg_sessions() as db:
        row = db.get(SewingRecord, first["id"])
        work = db.get(WorkOrder, case["sewing_id"])
        assignment = db.get(SewingAssignment, case["assignment_id"])
        packaging = db.get(WorkOrder, case["packaging_id"])
        order = db.get(ProductionOrder, case["order_id"])
        assert (row.input_qty, row.passed_qty, row.failed_qty, row.assignment_applied_qty) == (7, 6, 1, 7)
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty) == (7, 6, 6, 1)
        assert (assignment.completed_qty, assignment.status) == (7, "in_progress")
        assert packaging.status == "in_progress" and order.status == "packaging"
        assert work.planned_output_qty == 6
        assert packaging.department_id == db.query(Department.id).filter_by(code="ECP").scalar()
        assert db.query(WasteRecord).filter_by(work_order_id=work.id, waste_type="sewing_defect").count() == 1
        assert db.query(Notification).filter_by(user_id=case["package_user_id"], title="Awaiting packaging").count() == 1
        audit = db.query(AuditLog).filter_by(entity_type="SewingRecord", entity_id=row.id, action="create").one()
        assert audit.user_id == case["actor_id"]
        assert audit.old_value_json is None
        assert audit.new_value_json == {
            "work_order_id": case["sewing_id"], "production_batch_id": None,
            "input_qty": 7, "passed_qty": 6, "size_quantities": [],
        }
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == 1
        assert db.query(WorkOrder).filter_by(id=case["sewing_id"]).one().actual_output_qty == 6
        assert db.query(SewingAssignment).filter_by(id=case["assignment_id"]).one().completed_qty == 7
        assert db.query(WorkOrder).filter_by(id=case["packaging_id"]).one().department_id == (
            db.query(Department.id).filter_by(code="ECP").scalar()
        )
    chain(customer_pg_sessions)


def test_pg_band_output_uses_the_same_operation_and_preserves_retry_contract(customer_pg_sessions, sewing_case):
    from app.api.routes.sewing_bands import record_output

    case = sewing_case
    key = "sewing-band-output-" + uuid4().hex
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        actor.sewing_band_id = case["flow_id"]
        db.get(Bundle, case["bundle_id"]).status = "received_sewing"
        db.commit()
        bind_idempotency_identity(db, actor)
        payload = _payload(case, passed=8, failed=2, input_qty=0, sewn_qty=10)
        first = record_output(case["assignment_id"], payload, db, actor, key)
        assert record_output(case["assignment_id"], payload, db, actor, key) == first
    with customer_pg_sessions() as db:
        assert db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).count() == 1
        assert db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).one().assignment_applied_qty == 10
        assert db.get(WorkOrder, case["sewing_id"]).actual_input_qty == 50
        assert db.query(WasteRecord).filter_by(work_order_id=case["sewing_id"], quantity=2).count() == 1
        record = db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).one()
        audit = db.query(AuditLog).filter_by(entity_type="SewingRecord", entity_id=record.id, action="create").one()
        assert audit.user_id == case["actor_id"]
        assert audit.new_value_json == {
            "work_order_id": case["sewing_id"], "production_batch_id": None,
            "input_qty": 0, "passed_qty": 8, "size_quantities": [],
        }
    chain(customer_pg_sessions)


def test_pg_sewing_output_refusals_have_no_persistent_effects(customer_pg_sessions, sewing_case):
    case = sewing_case
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        actor.session_factory_code = "MIL"
        with pytest.raises(HTTPException) as denied:
            post_sewing(_payload(case), db, actor, None)
        assert denied.value.status_code == 403
        db.rollback()
        actor = db.get(User, case["actor_id"])
        actor.session_factory_code = "ECO"
        with pytest.raises(HTTPException) as over_limit:
            post_sewing(_payload(case, input_qty=51, sewn_qty=51, passed=51, failed=0), db, actor, None)
        assert over_limit.value.status_code == 400
        db.rollback()
    with customer_pg_sessions() as db:
        assert db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).count() == 0
        assert db.query(WasteRecord).filter_by(work_order_id=case["sewing_id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="SewingRecord", user_id=case["actor_id"]).count() == 0
        assert db.query(Notification).filter_by(user_id=case["package_user_id"]).count() == 0


def test_pg_real_accessory_gate_refusal_rolls_back_flushed_block_then_retry(customer_pg_sessions, sewing_case):
    case = sewing_case
    key = "accessory-gate-" + uuid4().hex
    with customer_pg_sessions() as db:
        model = db.get(Model, db.get(ProductionOrder, case["order_id"]).model_id)
        accessory = Item(
            sku="SEW-ACCESSORY-" + uuid4().hex[:12], name="Sewing gate accessory",
            category="accessory", unit="pcs",
        )
        db.add(accessory)
        db.flush()
        requirement = ModelBOM(
            model_id=model.id, item_id=accessory.id, quantity_per_piece=1,
            unit="pcs", waste_percent=0,
        )
        db.add(requirement)
        db.commit()

        actor = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, actor)
        with pytest.raises(HTTPException) as refused:
            post_sewing(_payload(case), db, actor, key)
        assert refused.value.status_code == 409
        db.rollback()

    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        work = db.get(WorkOrder, case["sewing_id"])
        packaging = db.get(WorkOrder, case["packaging_id"])
        assignment = db.get(SewingAssignment, case["assignment_id"])
        order = db.get(ProductionOrder, case["order_id"])
        assert not work.is_blocked and work.block_reason is None
        assert (work.actual_input_qty, work.actual_output_qty, work.passed_qty, work.failed_qty) == (0, 0, 0, 0)
        assert (assignment.completed_qty, assignment.status) == (0, "planned")
        assert packaging.department_id == db.query(Department.id).filter_by(code="PKG").scalar()
        assert (packaging.planned_input_qty, packaging.planned_output_qty, packaging.status) == (50, 50, "waiting")
        assert order.status == "sewing"
        assert db.query(SewingRecord).filter_by(work_order_id=work.id).count() == 0
        assert db.query(WasteRecord).filter_by(work_order_id=work.id).count() == 0
        assert db.query(Notification).filter_by(user_id=case["package_user_id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="SewingRecord", user_id=case["actor_id"]).count() == 0
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.key.like("accessory-gate-%")).count() == 0
        assert db.query(StockMovement).filter(StockMovement.reference_type == "ProductionOrderAccessory").count() == 0
        assert db.query(ModelBOM).filter_by(id=requirement.id).count() == 1
        assert db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == 0
        # Satisfy the existing accessory handoff through its actual issuer; keep
        # the required BOM in place and retry the same idempotency key.
        from app.models.inventory_service import issue_accessories_to_production_order

        issue_accessories_to_production_order(
            db, production_order_id=case["order_id"], user_id=actor.id,
            lines=[{
                "item_id": 0, "manual": True, "item_sku": accessory.sku,
                "item_name": accessory.name, "quantity": 50, "unit": "pcs",
            }],
        )
        db.flush()
        assert db.get(ModelBOM, requirement.id) is not None
        assert db.query(ManualAccessoryIssue).filter_by(production_order_id=case["order_id"]).count() == 1
        db.commit()
        actor = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, actor)
        result = post_sewing(_payload(case), db, actor, key)
        assert result["id"]


def test_pg_zero_defect_output_does_not_create_waste_or_advance_its_sequence(customer_pg_sessions, sewing_case):
    case = sewing_case
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, actor)
        sequence = db.execute(text("SELECT pg_get_serial_sequence('waste_records', 'id')")).scalar_one()
        assert sequence
        before = db.execute(text(f"SELECT last_value, is_called FROM {sequence}")).one()
        result = post_sewing(
            _payload(case, passed=5, failed=0, input_qty=5, sewn_qty=5), db, actor,
            "sewing-zero-defect-" + uuid4().hex,
        )
        assert result["id"]
        after = db.execute(text(f"SELECT last_value, is_called FROM {sequence}")).one()
        assert after == before
        assert db.query(WasteRecord).filter_by(work_order_id=case["sewing_id"]).count() == 0


def test_pg_work_order_status_filter_uses_enum_and_wire_value(customer_pg_sessions, sewing_case):
    from app.api.routes.production import list_wos
    from app.libs.dto.production.production import WorkOrderOut
    from app.libs.enums.production import WorkOrderStatus

    case = sewing_case
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        rows = list_wos(db, actor, status=WorkOrderStatus.IN_PROGRESS)
        sewing = next(row for row in rows if row.id == case["sewing_id"])
        assert sewing.status == WorkOrderStatus.IN_PROGRESS.value
        wire = WorkOrderOut.model_validate(sewing)
        assert wire.status is WorkOrderStatus.IN_PROGRESS


@pytest.mark.parametrize(
    "failure_point",
    ["record", "accounting", "actual_input", "accessory_block", "department", "plans",
     "workflow", "waste", "notification", "audit", "idempotency", "outer_commit_call"],
)
def test_pg_sewing_output_writer_failure_rolls_back_and_retry_succeeds(
    customer_pg_sessions, sewing_case, monkeypatch, failure_point,
):
    from app.models.production import sewing_service
    from app.models import audit_service, idempotency_service, workflow_service, inventory_service
    from app.schemas.production import sewing_output_persistence as persistence

    case = sewing_case
    with customer_pg_sessions() as db:
        actor = db.get(User, case["actor_id"])
        bind_idempotency_identity(db, actor)
        work = db.get(WorkOrder, case["sewing_id"])
        work.is_blocked = True
        work.block_reason = inventory_service.ACCESSORY_SEWING_BLOCK_REASON
        db.commit()
        key = "sewing-failure-" + failure_point + "-" + uuid4().hex
        payload = _payload(case)
        original_commit = db.commit

        def fail_after(original):
            def wrapped(*args, **kwargs):
                original(*args, **kwargs)
                raise RuntimeError("injected sewing participant failure")
            return wrapped

        targets = {
            "record": (persistence, "insert_sewing_output"),
            "accounting": (persistence, "apply_sewing_output_accounting"),
            "actual_input": (sewing_service, "sync_sewing_input"),
            "accessory_block": (persistence, "set_work_order_accessory_block"),
            "department": (persistence, "set_work_order_department"),
            "plans": (persistence, "raise_sewing_output_plans"),
            "workflow": (sewing_service, "advance_workflow"),
            "waste": (sewing_service, "create_waste_record"),
            "notification": (workflow_service, "add_notification_row"),
            "audit": (audit_service, "add_audit_log_rows"),
            "idempotency": (idempotency_service, "insert_idempotency_record"),
        }
        with monkeypatch.context() as patch:
            if failure_point == "outer_commit_call":
                def fail_commit():
                    raise RuntimeError("injected outer commit call failure")
                patch.setattr(db, "commit", fail_commit)
            else:
                module, name = targets[failure_point]
                original = getattr(module, name)
                patch.setattr(module, name, fail_after(original))
            with pytest.raises(RuntimeError, match="injected (?:sewing|outer commit call)"):
                post_sewing(payload, db, actor, key)
        db.rollback()
        assert db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).count() == 0
        assert db.query(WasteRecord).filter_by(work_order_id=case["sewing_id"]).count() == 0
        assert db.query(AuditLog).filter_by(entity_type="SewingRecord", user_id=case["actor_id"]).count() == 0
        assert db.query(Notification).filter_by(user_id=case["package_user_id"]).count() == 0
        assert db.query(IdempotencyRecord).filter_by(key=key).count() == 0
        work = db.query(WorkOrder).filter_by(id=case["sewing_id"]).populate_existing().one()
        package = db.query(WorkOrder).filter_by(id=case["packaging_id"]).populate_existing().one()
        assignment = db.query(SewingAssignment).filter_by(id=case["assignment_id"]).populate_existing().one()
        assert work.is_blocked and work.actual_output_qty == 0 and work.passed_qty == 0
        assert package.department_id == db.query(Department.id).filter_by(code="PKG").scalar()
        assert package.planned_input_qty == 50 and assignment.completed_qty == 0
        db.commit = original_commit
        result = post_sewing(payload, db, actor, key)
        assert result["id"]
    with customer_pg_sessions() as db:
        assert db.query(SewingRecord).filter_by(work_order_id=case["sewing_id"]).count() == 1
        assert db.query(AuditLog).filter_by(
            entity_type="SewingRecord", action="create", user_id=case["actor_id"],
        ).count() == 1
        assert db.query(WasteRecord).filter_by(work_order_id=case["sewing_id"]).count() == 1
    chain(customer_pg_sessions)


def test_pg_sewing_output_waits_on_real_work_order_lock(customer_pg_sessions, sewing_case, record_property):
    sessions = customer_pg_sessions
    case = sewing_case
    started = Event()
    waiter_pid: dict[str, int] = {}
    with sessions() as holder:
        holder.query(WorkOrder).filter_by(id=case["sewing_id"]).with_for_update(of=WorkOrder).one()
        blocker_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()
        def submit():
            with sessions() as contender:
                actor = contender.get(User, case["actor_id"])
                pid = contender.execute(text("SELECT pg_backend_pid()")).scalar_one()
                waiter_pid["pid"] = int(pid)
                started.set()
                response = post_sewing(_payload(case, passed=1, failed=0, input_qty=1, sewn_qty=1),
                                       contender, actor, None)
                return pid, response
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            assert started.wait(8)
            deadline = monotonic() + 8
            observed = None
            while monotonic() < deadline:
                with sessions() as observer:
                    state = observer.execute(text(
                        "SELECT wait_event_type, wait_event, pg_blocking_pids(:pid) AS blockers "
                        "FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": waiter_pid["pid"]}).mappings().one_or_none()
                    if state and state["wait_event_type"] == "Lock" and blocker_pid in state["blockers"]:
                        observed = dict(state)
                        break
                if future.done():
                    break
                sleep(0.025)
            holder.rollback()
            pid, result = future.result(timeout=15)
            assert result["id"]
    assert observed is not None, "output request did not wait on the locked Sewing WorkOrder"
    record_property("sewing_output_lock_witness", json.dumps({
        "blocker_pid": blocker_pid, "waiter_pid": pid,
        "wait_event_type": observed["wait_event_type"], "wait_event": observed["wait_event"],
        "blockers": list(observed["blockers"]),
    }, sort_keys=True))
    chain(sessions)


def test_pg_band_output_waits_on_same_work_order_lock(customer_pg_sessions, sewing_case, record_property):
    from app.api.routes.sewing_bands import record_output

    sessions = customer_pg_sessions
    case = sewing_case
    with sessions() as setup:
        actor = setup.get(User, case["actor_id"])
        actor.sewing_band_id = case["flow_id"]
        setup.get(Bundle, case["bundle_id"]).status = "received_sewing"
        setup.commit()

    started = Event()
    waiter_pid: dict[str, int] = {}
    with sessions() as holder:
        holder.query(WorkOrder).filter_by(id=case["sewing_id"]).with_for_update(of=WorkOrder).one()
        blocker_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar_one()

        def submit():
            with sessions() as contender:
                actor = contender.get(User, case["actor_id"])
                bind_idempotency_identity(contender, actor)
                pid = contender.execute(text("SELECT pg_backend_pid()")).scalar_one()
                waiter_pid["pid"] = int(pid)
                started.set()
                return pid, record_output(
                    case["assignment_id"], _payload(case, passed=1, failed=0, input_qty=0, sewn_qty=1),
                    contender, actor, "band-lock-" + uuid4().hex,
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            assert started.wait(8)
            deadline = monotonic() + 8
            observed = None
            while monotonic() < deadline:
                with sessions() as observer:
                    state = observer.execute(text(
                        "SELECT wait_event_type, wait_event, pg_blocking_pids(:pid) AS blockers "
                        "FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": waiter_pid["pid"]}).mappings().one_or_none()
                    if state and state["wait_event_type"] == "Lock" and blocker_pid in state["blockers"]:
                        observed = dict(state)
                        break
                if future.done():
                    break
                sleep(0.025)
            holder.rollback()
            pid, result = future.result(timeout=15)
            assert result["id"]
    assert observed is not None, "band output request did not wait on the locked Sewing WorkOrder"
    record_property("sewing_band_output_lock_witness", json.dumps({
        "blocker_pid": blocker_pid, "waiter_pid": pid,
        "wait_event_type": observed["wait_event_type"], "wait_event": observed["wait_event"],
        "blockers": list(observed["blockers"]),
    }, sort_keys=True))
    chain(sessions)
