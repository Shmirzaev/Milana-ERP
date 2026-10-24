"""Real PostgreSQL receipt locks, reconciliation, audit and sibling preservation."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes.bundles import SewingManualReceiveIn, manual_receive_sewing
from app.models import AuditLog, Bundle, BundleScanLog, CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, SewingRecord, User, WorkOrder
from app.services.sewing_progress import reconcile_sewing_order
from app.tests.test_password_change_races import password_change_postgres_sessions  # noqa: F401


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
@pytest.mark.parametrize('printing_loss', [0, 28])
def test_postgres_later_receipt_reopens_and_preserves_history(password_change_postgres_sessions, factory, printing_loss):
    from app.models import PrintingRecord
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
        db.commit()
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
        result = manual_receive_sewing(SewingManualReceiveIn(production_order_id=order_id,
            production_batch_id=batch_id, model_id=model.id, factory_code=factory), db, actor)
        assert result['received_quantity'] == 128
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
        from app.models import SewingFlow
        from app.schemas.production import PackagingRecordIn, SewingRecordIn
        from app.schemas.sewing_assignment import SewingAssignmentIn
        flow = SewingFlow(factory_code=factory, code='PG-' + marker, name='PostgreSQL later line ' + marker)
        db.add(flow)
        db.commit()
        actor = db.get(User, actor_id)
        actor.session_factory_code = factory
        assignment = create_assignment(sewing_id, SewingAssignmentIn(work_order_id=sewing_id,
            production_batch_id=batch_id, sewing_flow_id=flow.id, quantity=128-printing_loss), db, actor)
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
        sewing.status = 'cancelled'
        db.commit()
        reconcile_sewing_order(db, order_id)
        db.commit()
        assert sewing.status == 'cancelled'
