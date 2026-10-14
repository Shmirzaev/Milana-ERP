"""Usluga size corrections retain the accepted batch and Sewing handoff."""
import pytest

from app.core.security import hash_password
from app.models import (
    AuditLog, Bundle, BundleScanLog, CuttingRecord, Department, PackagingReceipt, ProductionBatch,
    Role, SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder,
)
from app.tests.conftest import TestSessionLocal
from app.tests.test_usluga import _create_usluga_order, _login_eco


@pytest.fixture
def accepted(client):
    _login_eco(client)
    model, order = _create_usluga_order(client, quantity=1212)
    work = {row['operation']: row['id'] for row in order['work_orders']}
    split = client.post(f"/api/work-orders/{work['cutting']}/split-batches", json={
        'batches': [{'name': 'Nastil 1', 'planned_quantity': 606},
                    {'name': 'Nastil 2', 'planned_quantity': 606}],
    })
    assert split.status_code == 200, split.text
    batches = client.get(f"/api/work-orders/{work['cutting']}/cutting-batch-progress").json()['items']
    bid, sibling = [row['id'] for row in batches]
    response = client.post('/api/cutting/records', json={
        'work_order_id': work['cutting'], 'production_batch_id': bid,
        'model_bom_id': model['main_bom_id'], 'input_quantity': 405, 'input_unit': 'kg',
        'cut_pieces': 606, 'passed_pieces': 606, 'defective_pieces': 0,
        'waste_quantity': 55, 'waste_unit': 'kg',
        'bundles': [{'color': 'Dark Blue', 'size': str(size), 'quantity': 101,
                     'count': 1, 'next': 'sewing'} for size in range(44, 55, 2)],
    })
    assert response.status_code == 201, response.text
    rid = response.json()['id']
    assert client.post(f'/api/cutting/records/{rid}/approve-usluga-batch', json={}).status_code == 200
    with TestSessionLocal() as db:
        flow = db.query(SewingFlow).filter_by(factory_code='ECO').first()
        if not flow:
            flow = SewingFlow(code='ECO-CORRECTION', name='Eco correction line', factory_code='ECO', capacity=5000)
            db.add(flow)
            db.commit()
        flow_id = flow.id
    response = client.post(f'/api/bundles/sewing-batches/{bid}/accept', json={'sewing_flow_id': flow_id})
    assert response.status_code == 200, response.text
    aid = response.json()['sewing_assignment_id']
    with TestSessionLocal() as db:
        # Completed sibling and cancelled historic assignment must stay intact.
        db.add_all([
            SewingAssignment(work_order_id=work['sewing'], production_batch_id=sibling,
                             sewing_flow_id=flow_id, quantity=606, completed_qty=606, status='completed'),
            SewingAssignment(work_order_id=work['sewing'], production_batch_id=bid,
                             sewing_flow_id=flow_id, quantity=606, status='cancelled'),
            SewingRecord(work_order_id=work['sewing'], production_batch_id=sibling,
                         sewn_qty=606, passed_qty=606),
        ])
        department = db.query(Department).filter_by(code='ECT').one()
        role = Role(name='Quantity correction Cutting', permissions=['cutting.records'])
        db.add(role)
        db.flush()
        user = User(name='Cutting operator', email='quantity-test@example.com',
                    password_hash=hash_password('correction-test-password'), role_id=role.id,
                    factory_code='ECO', department_id=department.id, is_active=True)
        db.add(user)
        db.commit()
        uid = user.id
        identities = [(b.id, b.barcode, b.status) for b in db.query(Bundle).filter_by(cutting_record_id=rid).order_by(Bundle.id)]
        scans = db.query(BundleScanLog).count()
    response = client.post('/api/auth/login-json', json={
        'email': 'quantity-test@example.com', 'password': 'correction-test-password', 'factory_code': 'ECO',
    })
    assert response.status_code == 200, response.text
    return dict(rid=rid, bid=bid, sibling=sibling, aid=aid, uid=uid, work=work, identities=identities, scans=scans)


def _increase(client, state, quantity=110):
    return client.patch(f"/api/cutting/records/{state['rid']}/usluga-size-counts", json={
        'sizes': [{'color': 'Dark Blue', 'size': str(size), 'quantity': quantity} for size in range(44, 55, 2)],
    })


def test_cutting_operator_increases_accepted_nastil_and_preserves_sibling(client, accepted):
    response = _increase(client, accepted)
    assert response.status_code == 200, response.text
    assert {row['quantity'] for row in response.json()['size_counts']} == {110}
    # Repeating the request does not increase plans or assignment a second time.
    assert _increase(client, accepted).status_code == 200
    with TestSessionLocal() as db:
        rec = db.get(CuttingRecord, accepted['rid'])
        assert (rec.cut_pieces, rec.passed_pieces, rec.total_bundled_quantity) == (660, 660, 660)
        assert (float(rec.input_quantity), float(rec.waste_quantity), rec.approval_status) == (405, 55, 'approved')
        assert db.get(ProductionBatch, accepted['bid']).planned_quantity == 660
        assert db.get(ProductionBatch, accepted['sibling']).planned_quantity == 606
        assert db.get(SewingAssignment, accepted['aid']).quantity == 660
        assert [(r.quantity, r.completed_qty, r.status) for r in db.query(SewingAssignment).filter_by(production_batch_id=accepted['sibling'])] == [(606, 606, 'completed')]
        assert db.query(SewingAssignment).filter_by(production_batch_id=accepted['bid'], status='cancelled').one().quantity == 606
        assert [(b.id, b.barcode, b.status) for b in db.query(Bundle).filter_by(cutting_record_id=rec.id).order_by(Bundle.id)] == accepted['identities']
        assert db.query(BundleScanLog).count() == accepted['scans']
        for wid in accepted['work'].values():
            assert db.get(WorkOrder, wid).planned_output_qty == 1266
        assert db.query(AuditLog).filter_by(action='update_usluga_bundle_size_counts', entity_id=rec.id).count() == 2
    sheet = client.get(f"/api/cutting/records/{accepted['rid']}/production-sheet")
    assert sheet.status_code == 200, sheet.text
    assert '660' in sheet.text and '110' in sheet.text
    _login_eco(client)
    sewn = client.post('/api/sewing/records', json={
        'work_order_id': accepted['work']['sewing'], 'production_batch_id': accepted['bid'],
        'sewing_assignment_id': accepted['aid'], 'input_qty': 660, 'sewn_qty': 660, 'passed_qty': 660,
        'size_quantities': [{'size': str(size), 'quantity': 110} for size in range(44, 55, 2)],
    })
    assert sewn.status_code == 201, sewn.text
    received = client.post('/api/packaging/receive-from-sewing', json={
        'work_order_id': accepted['work']['packaging'], 'production_batch_id': accepted['bid'],
        'quantity': 660,
    })
    assert received.status_code == 201, received.text
    assert _increase(client, accepted, 111).status_code == 409


@pytest.mark.parametrize('blocker', ['permission', 'factory', 'completed', 'downstream', 'packaging', 'closed_work'])
def test_accepted_nastil_guards(client, accepted, blocker):
    with TestSessionLocal() as db:
        if blocker == 'permission':
            db.get(User, accepted['uid']).role.permissions = []
        elif blocker == 'factory':
            db.get(User, accepted['uid']).factory_code = 'MIL'
        elif blocker == 'completed':
            db.get(SewingAssignment, accepted['aid']).status = 'completed'
        elif blocker == 'closed_work':
            db.get(WorkOrder, accepted['work']['sewing']).status = 'completed'
        elif blocker == 'packaging':
            db.add(PackagingReceipt(
                work_order_id=accepted['work']['packaging'], source_work_order_id=accepted['work']['sewing'],
                production_order_id=db.get(ProductionBatch, accepted['bid']).production_order_id,
                production_batch_id=accepted['bid'], bundle_id=accepted['identities'][0][0],
                quantity=101, receive_method='scan', packaging_department_code='ECP',
            ))
        else:
            db.add(SewingRecord(work_order_id=accepted['work']['sewing'], production_batch_id=accepted['bid'],
                                input_qty=700, sewn_qty=700, passed_qty=700))
        db.commit()
    response = _increase(client, accepted)
    assert response.status_code in (403, 409), response.text
    with TestSessionLocal() as db:
        assert db.get(CuttingRecord, accepted['rid']).cut_pieces == 606
        assert db.get(ProductionBatch, accepted['bid']).planned_quantity == 606
        assert db.get(SewingAssignment, accepted['aid']).quantity == 606
        assert {b.quantity for b in db.query(Bundle).filter_by(cutting_record_id=accepted['rid'])} == {101}
