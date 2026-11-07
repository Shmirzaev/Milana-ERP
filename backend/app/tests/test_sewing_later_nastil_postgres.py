"""Real PostgreSQL receipt locks, reconciliation, audit and sibling preservation."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.bundles import SewingManualReceiveIn, manual_receive_sewing
from app.schemas import AuditLog, Bundle, BundleScanLog, CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, SewingRecord, User, WorkOrder
from app.models.sewing_progress_service import reconcile_sewing_order
from app.tests.test_password_change_races import password_change_postgres_sessions  # noqa: F401


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
@pytest.mark.parametrize(('printing_loss', 'receipt_line'), [(0, False), (28, False), (0, True), (28, True)])
def test_postgres_later_receipt_reopens_and_preserves_history(password_change_postgres_sessions, factory, printing_loss, receipt_line):
    from app.schemas import PrintingRecord, SewingAssignment, SewingFlow
    sessions, _ = password_change_postgres_sessions
    marker = uuid4().hex[:10]
    with sessions() as db:
        actor = User(name='Later Nastil QA', email=f'qa-{marker}@example.invalid', password_hash='test-only',
                     factory_code=factory, extra_permissions=['*'])
        model = Model(code=f'LATER-{marker}', name='Later Nastil PostgreSQL')
        cut_dept = Department(code='C-' + marker, name='Test Cutting ' + marker)
        sew_dept = db.query(Department).filter_by(code=factory).first()
        if sew_dept is None:
            sew_dept = Department(code=factory, name=factory)
            db.add(sew_dept)
        packing_code = {'MIL': 'PKG', 'BST': 'BPK', 'ECO': 'ECP'}[factory]
        packing_dept = db.query(Department).filter_by(code=packing_code).first()
        if packing_dept is None:
            packing_dept = Department(code=packing_code, name=packing_code)
            db.add(packing_dept)
        db.add_all([actor, model, cut_dept])
        db.flush()
        order = ProductionOrder(production_no='LATER-' + marker, production_type='branded_stock',
                                model_id=model.id, planned_quantity=600, status='packaging')
        db.add(order)
        db.flush()
        batches = [ProductionBatch(production_order_id=order.id, batch_no=f'{marker}-{i}',
                                   batch_index=i, name=f'Nastil {i}', planned_quantity=128) for i in (1, 2)]
        db.add_all(batches)
        cut = WorkOrder(production_order_id=order.id, operation='cutting', department_id=cut_dept.id,
                        planned_output_qty=600, passed_qty=256, failed_qty=472, status='completed')
        sewing = WorkOrder(production_order_id=order.id, operation='sewing', department_id=sew_dept.id,
                           planned_output_qty=600, actual_input_qty=128, actual_output_qty=128,
                           passed_qty=128, status='completed', end_time=datetime.now(timezone.utc)-timedelta(days=2))
        db.add_all([cut, sewing])
        packing = WorkOrder(production_order_id=order.id, operation='packaging', department_id=packing_dept.id,
                            status='waiting', planned_input_qty=600, planned_output_qty=600)
        db.add(packing)
        db.flush()
        for batch in batches:
            db.add(CuttingRecord(work_order_id=cut.id, production_batch_id=batch.id, cut_pieces=128, passed_pieces=128))
        if printing_loss:
            printing = WorkOrder(production_order_id=order.id, operation='printing', department_id=cut_dept.id,
                                 status='completed', planned_output_qty=128, passed_qty=128-printing_loss,
                                 failed_qty=printing_loss)
            db.add(printing)
            db.flush()
            db.add(PrintingRecord(work_order_id=printing.id, production_batch_id=batches[1].id,
                                 input_qty=128, printed_qty=128, passed_qty=128-printing_loss, rejected_qty=printing_loss))
        first = SewingRecord(work_order_id=sewing.id, production_batch_id=batches[0].id,
                             input_qty=128, sewn_qty=128, passed_qty=128)
        db.add(first)
        db.add(Bundle(production_order_id=order.id, production_batch_id=batches[0].id,
                      model_id=model.id, bundle_no=f'{marker}-old', barcode=f'{marker}-old-bar',
                      color='white', size='M', quantity=128, status='received_sewing', sewing_factory_code=factory,
                      current_department_id=sew_dept.id, next_department_id=sew_dept.id))
        bundles = [Bundle(production_order_id=order.id, production_batch_id=batches[1].id,
                          model_id=model.id, bundle_no=f'{marker}-{i}', barcode=f'{marker}-bar-{i}',
                          color='white', size='M', quantity=32, status='created', sewing_factory_code=factory,
                          current_department_id=cut_dept.id, next_department_id=sew_dept.id) for i in range(4)]
        db.add_all(bundles)
        flow = SewingFlow(factory_code=factory, code='PG-' + marker, name='PostgreSQL later line ' + marker)
        db.add(flow)
        db.commit()
        flow_id = flow.id
        actor_id, order_id, sewing_id, packing_id, batch_id, first_id = actor.id, order.id, sewing.id, packing.id, batches[1].id, first.id
        identities = [(b.id, b.barcode, b.quantity) for b in bundles]
    with sessions() as blocker, sessions() as contender:
        blocker.query(WorkOrder).filter_by(id=sewing_id).with_for_update(of=WorkOrder).one()
        with pytest.raises(HTTPException) as denied:
            reconcile_sewing_order(contender, order_id)
        assert denied.value.status_code == 409
        contender.rollback()
        blocker.rollback()
    with sessions() as db:
        actor = db.get(User, actor_id)
        actor.session_factory_code = factory
        def receipt():
            with sessions() as writer:
                worker_actor = writer.get(User, actor_id)
                worker_actor.session_factory_code = factory
                barrier.wait(timeout=5)
                return manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                    production_batch_id=batch_id, model_id=model.id, factory_code=factory, sewing_flow_id=flow_id), writer, worker_actor)

        if receipt_line:
            barrier = Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: receipt(), range(2)))
            assert sorted(item['received_count'] for item in results) == [0, 4]
            assert len({item['sewing_assignment_id'] for item in results}) == 1
            result = max(results, key=lambda item: item['received_quantity'])
        else:
            result = manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                production_batch_id=batch_id, model_id=model.id, factory_code=factory), db, actor)
        assert result['received_quantity'] == 128
        if receipt_line:
            assigned_id = result['sewing_assignment_id']
            # Bounded retry challenge on the actual PostgreSQL row locks.
            for _ in range(12):
                retry = manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                    production_batch_id=batch_id, model_id=model.id, factory_code=factory, sewing_flow_id=flow_id), db, actor)
                assert retry['received_count'] == 0 and retry['sewing_assignment_id'] == assigned_id
            assert db.query(SewingAssignment).filter_by(work_order_id=sewing_id, production_batch_id=batch_id).count() == 1
    with sessions() as db:
        sewing = db.get(WorkOrder, sewing_id)
        assert sewing.status == 'in_progress' and sewing.end_time is None
        assert sewing.passed_qty == 128 and sewing.actual_input_qty == 256
        assert db.get(SewingRecord, first_id).passed_qty == 128
        actual = db.query(Bundle).filter(Bundle.id.in_([row[0] for row in identities])).order_by(Bundle.id).all()
        assert [(b.id, b.barcode, b.quantity) for b in actual] == identities
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_([b.id for b in actual])).count() == 4
        assert db.query(AuditLog).filter_by(action='reopen_later_nastil', entity_id=sewing_id).count() == 1
        # Reconciliation is idempotent and never reopens a cancelled work order.
        reconcile_sewing_order(db, order_id)
        db.commit()
        assert db.query(AuditLog).filter_by(action='reopen_later_nastil', entity_id=sewing_id).count() == 1
        from app.api.routes.production import post_packaging, post_sewing
        from app.api.routes.production_extra import create_assignment
        from app.libs.dto.production.production import PackagingRecordIn, SewingRecordIn
        from app.libs.dto.production.sewing_assignment import SewingAssignmentIn
        actor = db.get(User, actor_id)
        actor.session_factory_code = factory
        if receipt_line:
            assignment = db.get(SewingAssignment, assigned_id)
        else:
            assignment = create_assignment(sewing_id, SewingAssignmentIn(work_order_id=sewing_id,
                production_batch_id=batch_id, sewing_flow_id=flow_id, quantity=128-printing_loss), db, actor)
        post_sewing(SewingRecordIn(work_order_id=sewing_id, production_batch_id=batch_id,
            sewing_assignment_id=assignment.id, input_qty=128-printing_loss, sewn_qty=128-printing_loss,
            passed_qty=128-printing_loss), db, actor,
            idempotency_key=None)
        post_packaging(PackagingRecordIn(work_order_id=packing_id, production_batch_id=batch_id,
            input_qty=128-printing_loss, packed_qty=128-printing_loss), db, actor)
        assert db.get(WorkOrder, sewing_id).passed_qty == 256-printing_loss
        assert db.get(WorkOrder, sewing_id).status == 'completed'
        assert db.get(WorkOrder, packing_id).passed_qty == 128-printing_loss
        assert db.get(SewingRecord, first_id).passed_qty == 128
        assert (assignment.quantity, assignment.completed_qty, assignment.status) == (
            128-printing_loss, 128-printing_loss, 'completed')
        if receipt_line:
            completed_retry = manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                production_batch_id=batch_id, model_id=model.id, factory_code=factory, sewing_flow_id=flow_id), db, actor)
            assert completed_retry['received_count'] == 0
            assert completed_retry['sewing_assignment_id'] == assignment.id
            assert assignment.status == 'completed'
            assert db.get(WorkOrder, sewing_id).status == 'completed'
        sewing.status = 'cancelled'
        db.commit()
        reconcile_sewing_order(db, order_id)
        db.commit()
        assert sewing.status == 'cancelled'


def _postgres_receipt_case(sessions, count):
    from app.schemas import SewingFlow
    marker = uuid4().hex[:10]
    with sessions() as db:
        departments = {}
        for code in ("CUT", "MIL", "PKG"):
            department = db.query(Department).filter_by(code=code).first()
            if department is None:
                department = Department(code=code, name=code)
                db.add(department)
                db.flush()
            departments[code] = department.id
        actor = User(name="Receipt query QA", email=f"query-{marker}@example.invalid",
            password_hash="local-only", factory_code="MIL", extra_permissions=["*"])
        model = Model(code="QUERY-" + marker, name="Query QA")
        flow = SewingFlow(factory_code="MIL", code="QUERY-" + marker, name="Query QA line " + marker)
        db.add_all([actor, model, flow])
        db.flush()
        order = ProductionOrder(production_no="QUERY-" + marker, production_type="branded_stock",
            model_id=model.id, planned_quantity=count, status="cutting")
        db.add(order)
        db.flush()
        batch = ProductionBatch(production_order_id=order.id, batch_no="QUERY-" + marker,
            batch_index=1, planned_quantity=count)
        db.add(batch)
        db.flush()
        db.add_all([WorkOrder(production_order_id=order.id, operation="cutting", department_id=departments["CUT"],
            status="completed", passed_qty=count, planned_output_qty=count),
            WorkOrder(production_order_id=order.id, production_batch_id=batch.id, operation="sewing",
                department_id=departments["MIL"], status="waiting", planned_input_qty=count, planned_output_qty=count),
            WorkOrder(production_order_id=order.id, operation="packaging", department_id=departments["PKG"],
                status="waiting", planned_input_qty=count, planned_output_qty=count)])
        bundles = [Bundle(production_order_id=order.id, production_batch_id=batch.id, model_id=model.id,
            bundle_no=f"{marker}-{index}", barcode=f"{marker}-bar-{index}", color="white", size="M",
            quantity=1, status="created", sewing_factory_code="MIL",
            current_department_id=departments["CUT"], next_department_id=departments["MIL"]) for index in range(count)]
        db.add_all(bundles)
        db.commit()
        actor_id, order_id, batch_id, flow_id = actor.id, order.id, batch.id, flow.id
        bundle_ids = [bundle.id for bundle in bundles]
    return actor_id, order_id, batch_id, flow_id, bundle_ids


@pytest.mark.parametrize("mode", ["manual", "accept", "manual_line"])
def test_postgres_receipt_queries_stay_constant_with_real_audits(password_change_postgres_sessions, mode):
    from sqlalchemy import event
    from app.api.routes.bundles import SewingBatchAcceptIn, accept_sewing_batch
    from app.models.audit_service import verify_audit_hash_chain

    sessions, engine = password_change_postgres_sessions
    counts = []
    for count in (1, 50, 401):
        actor_id, order_id, batch_id, flow_id, bundle_ids = _postgres_receipt_case(sessions, count)
        with sessions() as db:
            actor = db.get(User, actor_id)
            actor.session_factory_code = "MIL"
            statements = []
            def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
                if statement.lstrip().upper().startswith("SELECT"):
                    statements.append(statement)
            event.listen(engine, "before_cursor_execute", capture)
            try:
                if mode == "accept":
                    result = accept_sewing_batch(batch_id, SewingBatchAcceptIn(sewing_flow_id=flow_id), db, actor)
                else:
                    result = manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                        production_batch_id=batch_id, factory_code="MIL", sewing_flow_id=flow_id if mode == "manual_line" else None), db, actor)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            assert result["received_count"] == count
            counts.append(len(statements))
            assert db.query(AuditLog).filter(AuditLog.entity_type == "Bundle", AuditLog.entity_id.in_(bundle_ids),
                AuditLog.action == "manual_receive_at_sewing").count() == (0 if mode == "accept" else count)
            assert verify_audit_hash_chain(db)["ok"]
    print(f"PostgreSQL {mode}: {counts} SELECTs for 1/50/401 bundles with real audits")
    assert len(set(counts)) == 1


@pytest.mark.parametrize("legacy_source", [False, True])
def test_postgres_receipt_sees_printing_published_while_waiting_for_locks(password_change_postgres_sessions, legacy_source):
    from queue import Queue
    from time import monotonic, sleep
    from sqlalchemy import text
    from app.api.routes.production import _resolve_record_batch_id
    from app.schemas import PrintingRecord, SewingAssignment

    sessions, engine = password_change_postgres_sessions
    actor_id, order_id, batch_id, flow_id, bundle_ids = _postgres_receipt_case(sessions, 1)
    with sessions() as db:
        bundle = db.get(Bundle, bundle_ids[0])
        bundle.quantity = 128
        batch = db.get(ProductionBatch, batch_id)
        batch.planned_quantity = 128
        printing = WorkOrder(production_order_id=order_id, production_batch_id=batch_id, operation="printing",
            department_id=db.query(Department.id).filter_by(code="CUT").scalar(), status="completed",
            planned_output_qty=128, passed_qty=100, failed_qty=28)
        db.add(printing)
        db.commit()
        printing_id = printing.id
    waiter_pid = Queue()

    def receive():
        with sessions() as db:
            actor = db.get(User, actor_id)
            actor.session_factory_code = "MIL"
            waiter_pid.put(db.scalar(text("SELECT pg_backend_pid()")))
            return manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
                production_batch_id=batch_id, factory_code="MIL", sewing_flow_id=flow_id), db, actor)

    with sessions() as publisher, ThreadPoolExecutor(max_workers=1) as pool:
        # A current route resolves and stores the exact batch even for a legacy
        # dedicated WO. Its FK obtains KEY SHARE; a retained legacy null source
        # lacks that lock, so only the bundle publication lock can serialize it.
        printing = publisher.get(WorkOrder, printing_id)
        resolved = _resolve_record_batch_id(publisher, printing, None, operation_name="printing")
        assert resolved == batch_id
        publisher.query(Bundle).filter(Bundle.id.in_(bundle_ids)).with_for_update(of=Bundle).all()
        publisher.add(PrintingRecord(work_order_id=printing_id,
            production_batch_id=None if legacy_source else resolved,
            input_qty=128, printed_qty=128, passed_qty=100, rejected_qty=28))
        publisher.flush()
        future = pool.submit(receive)
        pid = waiter_pid.get(timeout=5)
        try:
            with engine.connect() as inspector:
                deadline = monotonic() + 5
                while True:
                    state = inspector.execute(text("SELECT wait_event_type, query FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid}).one()
                    # pg_stat_activity snapshots are transaction-scoped.
                    inspector.commit()
                    if state.wait_event_type == "Lock":
                        break
                    assert monotonic() < deadline, "Receipt did not reach its publication lock wait"
                    sleep(0.01)
                if legacy_source:
                    # pg_stat_activity query text may truncate before FROM.
                    assert state.query.startswith("SELECT bundles.")
                else:
                    assert "FROM production_batches" in state.query
            publisher.commit()
            result = future.result(timeout=10)
        finally:
            publisher.rollback()
    with sessions() as db:
        assignment = db.get(SewingAssignment, result["sewing_assignment_id"])
        assert assignment.quantity == 100
        assert db.get(Bundle, bundle_ids[0]).quantity == 128
        assert db.get(Bundle, bundle_ids[0]).status == "received_sewing"
