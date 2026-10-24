"""A later Nastil must be reachable before its first Sewing output is posted."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models import AuditLog, Bundle, BundleScanLog, SewingAssignment, SewingFlow, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_sewing_output import _create, _pack
from app.tests.test_production_flow import _issue_required_accessories
from app.tests.test_sewing_nastil_completion import _sew
from app.tests.test_sewing_band_access import bands  # noqa: F401


def cut(client, headers, work, bid, factory='MIL'):
    response = client.post('/api/cutting/records', headers=headers, json={
        'work_order_id': work['cutting'], 'production_batch_id': bid,
        'input_quantity': 10, 'input_unit': 'kg', 'cut_pieces': 128,
        'passed_pieces': 128, 'defective_pieces': 0,
        'bundles': [{'color': 'white', 'size': 'M', 'quantity': 32, 'count': 4, 'sewing_factory': factory}],
    })
    assert response.status_code == 201, response.text


def first_finished(client, auth_headers, factory):
    po, work, first = _create(client, auth_headers)
    routed = client.patch(f"/api/work-orders/{work['cutting']}/sewing-factory", headers=auth_headers,
                          json={'sewing_factory_code': factory})
    assert routed.status_code == 200, routed.text
    cut(client, auth_headers, work, first, factory)
    done = client.post(f"/api/work-orders/{work['cutting']}/complete-cutting-shortage", headers=auth_headers)
    assert done.status_code == 200, done.text
    _issue_required_accessories(client, auth_headers, po['id'])
    headers = {'Authorization': 'Bearer ' + create_access_token(1, extra={'factory_code': factory})}
    assert _sew(client, headers, work['sewing'], first, 128).status_code == 201
    assert _pack(client, headers, work['packaging'], first, 120).status_code == 201
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, work['sewing'])
        assert wo.status == 'completed'
        wo.end_time = datetime.now(timezone.utc) - timedelta(days=2)
        flow = SewingFlow(factory_code=factory, code='LATER-' + uuid4().hex[:12], name='Later Nastil line')
        db.add(flow)
        db.commit()
        flow_id = flow.id
    return po, work, first, headers, flow_id


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
@pytest.mark.parametrize('receipt', ['manual', 'bundle', 'batch_qr'])
def test_later_nastil_receipt_assignment_sewing_packaging(client, auth_headers, factory, receipt):
    po, work, first, headers, flow_id = first_finished(client, auth_headers, factory)
    added = client.post(f"/api/work-orders/{work['cutting']}/extra-batch", headers=auth_headers,
                        json={'name': 'Nastil 2', 'planned_quantity': 128})
    assert added.status_code == 200, added.text
    second = added.json()['id']
    assert client.get(f"/api/work-orders/{work['sewing']}", headers=headers).json()['status'] == 'in_progress'
    # The original shortfall must not close a required, still-pending Nastil.
    assert client.post(f"/api/work-orders/{work['sewing']}/complete", headers=headers).status_code == 409
    cut(client, auth_headers, work, second, factory)
    with TestSessionLocal() as db:
        bundles = db.query(Bundle).filter_by(production_order_id=po['id'], production_batch_id=second).order_by(Bundle.id).all()
        ids = [b.id for b in bundles]
        identities = [(b.id, b.barcode, b.quantity) for b in bundles]
        # Historical stale state must recover from receipt, before posting output.
        wo = db.get(WorkOrder, work['sewing'])
        wo.status, wo.end_time = 'completed', datetime.now(timezone.utc) - timedelta(days=2)
        first_record = db.query(SewingRecord).filter_by(work_order_id=wo.id).one()
        preserved = (first_record.id, first_record.production_batch_id, first_record.passed_qty)
        db.commit()
    if receipt == 'batch_qr':
        response = client.post(f'/api/bundles/sewing-batches/{second}/accept', headers=headers,
                               json={'sewing_flow_id': flow_id})
    elif receipt == 'manual':
        response = client.post('/api/bundles/manual-receive-sewing', headers=headers,
                               json={'production_order_id': po['id'], 'production_batch_id': second, 'model_id': 1})
    else:
        for bid in ids:
            response = client.post(f'/api/bundles/{bid}/receive-sewing', headers=headers)
            assert response.status_code == 200, response.text
    assert response.status_code == 200, response.text
    dept = 'SEW' if factory == 'MIL' else factory
    floor = client.get('/api/inbox/department-orders', headers=headers,
                       params={'dept': dept, 'q': po['production_no'], 'tz': 'Asia/Tashkent'}).json()
    assert any(r.get('work_order_id', r.get('id')) == work['sewing'] and r['queue_kind'] == 'in_progress'
               for r in floor['rows'])
    available = client.get('/api/work-orders', headers=headers, params={
        'operation': 'sewing', 'only_active': True, 'only_received_sewing': True,
        'production_order_id': po['id'], 'sewing_factory_code': factory}).json()
    if receipt != 'batch_qr':
        assert next(r for r in available if r['production_batch_id'] == second)['assignable_qty'] == 128
        assigned = client.post(f"/api/work-orders/{work['sewing']}/assignments", headers=headers,
                               json={'work_order_id': work['sewing'], 'production_batch_id': second,
                                     'sewing_flow_id': flow_id, 'quantity': 128})
        assert assigned.status_code == 201, assigned.text
        aid = assigned.json()['id']
    else:
        aid = response.json()['sewing_assignment_id']
    # Repeated batch acceptance creates neither receipts nor assignments again.
    repeated = client.post(f'/api/bundles/sewing-batches/{second}/accept', headers=headers,
                           json={'sewing_flow_id': flow_id})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()['received_count'] == 0
    assert repeated.json()['sewing_assignment_id'] == aid
    assert _pack(client, headers, work['packaging'], second, 1).status_code == 400
    assert _sew(client, headers, work['sewing'], second, 128, aid).status_code == 201
    assert _pack(client, headers, work['packaging'], second, 128).status_code == 201
    with TestSessionLocal() as db:
        first_record = db.get(SewingRecord, preserved[0])
        assert (first_record.id, first_record.production_batch_id, first_record.passed_qty) == preserved
        bundles = db.query(Bundle).filter(Bundle.id.in_(ids)).order_by(Bundle.id).all()
        assert [(b.id, b.barcode, b.quantity) for b in bundles] == identities
        assert all(b.status == 'received_sewing' for b in bundles)
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(ids), BundleScanLog.scan_type == 'received_sewing').count() == 4
        assert db.query(SewingAssignment).filter_by(production_batch_id=second).count() == 1
        assert db.get(WorkOrder, work['sewing']).passed_qty == 256
        assert db.get(WorkOrder, work['packaging']).passed_qty == 248
        assert db.query(AuditLog).filter_by(entity_type='WorkOrder', entity_id=work['sewing'], action='reopen_later_nastil').count() >= 1


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
def test_later_passport_reopens_without_minting_bundles(client, auth_headers, factory):
    po, work, _, headers, _ = first_finished(client, auth_headers, factory)
    with TestSessionLocal() as db:
        before = db.query(Bundle).filter_by(production_order_id=po['id']).count()
    response = client.post('/api/cutting-passports', headers=auth_headers, json={
        'passport_no': 'LATER-' + uuid4().hex[:12], 'production_order_id': po['id'],
        'date': '2026-10-24T00:00:00Z', 'pieces': 128})
    assert response.status_code == 201, response.text
    state = client.get(f"/api/work-orders/{work['sewing']}", headers=headers).json()
    assert state['status'] == 'in_progress' and state['end_time'] is None
    with TestSessionLocal() as db:
        assert db.query(Bundle).filter_by(production_order_id=po['id']).count() == before
        assert db.get(WorkOrder, work['sewing']).passed_qty == 128


def test_completed_sibling_excess_cannot_complete_unsewn_nastil(client, auth_headers):
    from app.tests.test_sewing_nastil_completion import _setup
    work, first, second, headers = _setup(client, auth_headers, 'MIL')
    response = client.post('/api/sewing/records', headers=headers, json={
        'work_order_id': work['sewing'], 'production_batch_id': first,
        'input_qty': 300, 'sewn_qty': 600, 'passed_qty': 600})
    assert response.status_code == 201, response.text
    assert client.get(f"/api/work-orders/{work['sewing']}", headers=headers).json()['status'] == 'in_progress'
    assert client.post(f"/api/work-orders/{work['sewing']}/complete", headers=headers).status_code == 409
    assert _sew(client, headers, work['sewing'], second, 300).status_code == 201


def test_eco_band_can_receive_later_nastil_of_completed_shared_order(client, bands):
    from app.models import CuttingRecord, ProductionBatch
    wid, old_assignment, poid = bands['jobs'][0]
    with TestSessionLocal() as db:
        batches = [ProductionBatch(production_order_id=poid, batch_no=f'LATER-BAND-{i}',
                                   batch_index=i, planned_quantity=qty) for i, qty in ((1, 100), (2, 60))]
        db.add_all(batches)
        db.flush()
        first, second = [b.id for b in batches]
        old = db.get(SewingAssignment, old_assignment)
        old.production_batch_id, old.completed_qty, old.status = first, 100, 'completed'
        wo = db.get(WorkOrder, wid)
        wo.status, wo.passed_qty, wo.actual_output_qty = 'completed', 100, 100
        wo.planned_output_qty, wo.actual_input_qty = 160, 100
        old_bundle = db.get(Bundle, bands['bundles'][0])
        old_bundle.production_batch_id, old_bundle.status = first, 'received_sewing'
        cut_wo = db.query(WorkOrder).filter_by(production_order_id=poid, operation='cutting').one()
        cut_wo.passed_qty, cut_wo.planned_output_qty = 160, 160
        db.add_all([CuttingRecord(work_order_id=cut_wo.id, production_batch_id=first, cut_pieces=100, passed_pieces=100),
                    CuttingRecord(work_order_id=cut_wo.id, production_batch_id=second, cut_pieces=60, passed_pieces=60),
                    SewingRecord(work_order_id=wid, production_batch_id=first, sewing_assignment_id=old.id,
                                 input_qty=100, sewn_qty=100, passed_qty=100)])
        db.add(Bundle(production_order_id=poid, production_batch_id=second, bundle_no='LATER-BAND-NEW',
                      barcode='LATER-BAND-NEW-BAR', model_id=1, color='white', size='M', quantity=60,
                      sewing_factory_code='ECO', status='created', next_department_id=wo.department_id))
        db.commit()
    payload = {'production_order_id': poid, 'production_batch_id': second}
    _issue_required_accessories(client, bands['admin'], poid)
    received = client.post('/api/sewing-bands/receive', headers=bands['headers'][0], json=payload)
    assert received.status_code == 200, received.text
    denied = client.post('/api/sewing-bands/receive', headers=bands['headers'][1], json=payload)
    assert denied.status_code == 409
    jobs = client.get('/api/sewing-bands', headers=bands['headers'][0]).json()[0]['jobs']
    job = next(j for j in jobs if j['production_batch_id'] == second)
    output = client.post(f"/api/sewing-bands/{job['id']}/output", headers=bands['headers'][0], json={
        'work_order_id': wid, 'production_batch_id': second, 'sewing_assignment_id': job['id'],
        'input_qty': 0, 'sewn_qty': 60, 'passed_qty': 60})
    assert output.status_code == 200, output.text
    with TestSessionLocal() as db:
        assert db.get(SewingAssignment, old_assignment).status == 'completed'
        assert db.get(SewingAssignment, old_assignment).completed_qty == 100
        assert db.get(WorkOrder, wid).passed_qty == 160
