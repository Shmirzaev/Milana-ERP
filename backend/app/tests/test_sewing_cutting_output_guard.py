import pytest

from app.models import AuditLog, Department, Notification, PrintingRecord, ProductionBatch, SewingRecord, WasteRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_production_flow import _factory_headers
from app.tests.test_sewing_actual_output import make_batch, sew


def setup_order(factory, batched, *, cut=0):
    _, batch, orders = make_batch(plan=100, cut=cut)
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        wo.department_id = db.query(Department.id).filter_by(code=factory).scalar()
        wo.status = 'waiting'
        if not batched:
            if cut:
                from app.models import CuttingRecord
                db.query(CuttingRecord).filter_by(production_batch_id=batch).update({'production_batch_id': None})
            db.delete(db.get(ProductionBatch, batch))
            batch = None
        db.commit()
    return batch, orders


def state(orders):
    with TestSessionLocal() as db:
        return {
            'work': [(r.id, r.status, r.actual_input_qty, r.actual_output_qty, r.passed_qty, r.start_time, r.end_time)
                     for r in db.query(WorkOrder).filter(WorkOrder.id.in_(orders.values())).order_by(WorkOrder.id)],
            'counts': [db.query(model).count() for model in (SewingRecord, WasteRecord, Notification, AuditLog)],
        }


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
@pytest.mark.parametrize('batched', [False, True])
@pytest.mark.parametrize('input_qty,output,rework', [(100, 100, 0), (0, 100, 0), (0, 0, 1)])
def test_no_cutting_rejects_sewing_without_side_effects(client, factory, batched, input_qty, output, rework):
    batch, orders = setup_order(factory, batched)
    before = state(orders)
    response = client.post('/api/sewing/records', headers=_factory_headers(factory), json={
        'work_order_id': orders['sewing'], 'production_batch_id': batch,
        'input_qty': input_qty, 'sewn_qty': output, 'passed_qty': output, 'rework_qty': rework,
    })
    assert response.status_code == 400, response.text
    assert state(orders) == before


@pytest.mark.parametrize('batched', [False, True])
def test_printing_output_does_not_replace_missing_cutting(client, auth_headers, batched):
    batch, orders = setup_order('MIL', batched)
    with TestSessionLocal() as db:
        sew_wo = db.get(WorkOrder, orders['sewing'])
        prt = WorkOrder(production_order_id=sew_wo.production_order_id,
            department_id=db.query(Department.id).filter_by(code='PRT').scalar(),
            operation='printing', status='completed', passed_qty=100)
        db.add(prt); db.flush()
        if batched:
            db.add(PrintingRecord(work_order_id=prt.id, production_batch_id=batch,
                input_qty=100, printed_qty=100, passed_qty=100))
        db.commit()
    before = state(orders)
    response = sew(client, auth_headers, batch, orders, 0, 100)
    assert response.status_code == 400, response.text
    assert state(orders) == before


def test_another_nastils_cutting_does_not_allow_output_for_uncut_batch(client, auth_headers):
    _, batch, orders = make_batch(plan=100, cut=100)
    with TestSessionLocal() as db:
        original = db.get(ProductionBatch, batch)
        uncut = ProductionBatch(production_order_id=original.production_order_id,
            batch_index=2, batch_no=f'{original.production_order_id:04d}-02', planned_quantity=100)
        db.add(uncut); db.commit(); uncut_id = uncut.id
    before = state(orders)
    response = sew(client, auth_headers, uncut_id, orders, 0, 100)
    assert response.status_code == 400, response.text
    assert state(orders) == before


def test_missing_cutting_work_order_cannot_allow_output(client, auth_headers):
    batch, orders = setup_order('MIL', False)
    with TestSessionLocal() as db:
        db.delete(db.get(WorkOrder, orders['cutting']))
        db.commit()
    before = state(orders)
    response = sew(client, auth_headers, batch, orders, 0, 100)
    assert response.status_code == 400, response.text
    assert state(orders) == before


@pytest.mark.parametrize('batched', [False, True])
def test_output_only_and_overproduction_still_allowed_after_cutting(client, auth_headers, batched):
    batch, orders = setup_order('MIL', batched, cut=100)
    response = sew(client, auth_headers, batch, orders, 0, 110)
    assert response.status_code == 201, response.text
    assert client.get(f"/api/work-orders/{orders['packaging']}", headers=auth_headers).json()['planned_output_qty'] >= 110


@pytest.mark.parametrize('batched', [False, True])
def test_correction_cannot_increase_legacy_output_without_cutting(client, auth_headers, batched):
    batch, orders = setup_order('MIL', batched)
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        wo.actual_input_qty = wo.actual_output_qty = wo.passed_qty = 10
        row = SewingRecord(work_order_id=wo.id, production_batch_id=batch,
            input_qty=10, sewn_qty=10, passed_qty=10, assignment_applied_qty=0)
        db.add(row); db.commit(); rid = row.id
    before = state(orders)
    response = client.patch(f'/api/sewing/records/{rid}', headers=auth_headers, json={
        'expected_version': 0, 'input_qty': 10, 'sewn_qty': 20, 'passed_qty': 20,
    })
    assert response.status_code == 409, response.text
    assert state(orders) == before
    # Downward correction of bad history remains possible.
    response = client.patch(f'/api/sewing/records/{rid}', headers=auth_headers, json={
        'expected_version': 0, 'input_qty': 10, 'sewn_qty': 5, 'passed_qty': 5,
    })
    assert response.status_code == 200, response.text
