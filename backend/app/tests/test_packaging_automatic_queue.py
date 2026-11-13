"""Automatic Packaging queue consumes only proven Sewing, never acceptance history."""
import pytest
from sqlalchemy import event

from app.core.security import create_access_token
from app.schemas import Department, Package, PackagingReceipt, PackagingRecord, ProductionBatch, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal, test_engine
from app.tests.test_packaging_sewing_output import _create, _pack


def _queue(client, headers, oid, department="PKG"):
    response = client.get('/api/packaging/received-orders', headers=headers, params={'packaging_department_code': department})
    assert response.status_code == 200, response.text
    return [row for row in response.json() if row['production_order_id'] == oid]


@pytest.mark.parametrize('factory,department', [('MIL', 'PKG'), ('BST', 'BPK'), ('ECO', 'ECP')])
def test_automatic_queue_partial_and_legacy_receipt_history(client, auth_headers, factory, department):
    po, work, bid = _create(client, auth_headers)
    with TestSessionLocal() as db:
        pkg = db.get(WorkOrder, work['packaging'])
        pkg.department_id = db.query(Department.id).filter_by(code=department).scalar()
        pkg.status = 'ready'
        db.add(SewingRecord(work_order_id=work['sewing'], production_batch_id=bid, input_qty=100,
                            sewn_qty=100, passed_qty=95, failed_qty=5))
        db.commit()
    headers = {'Authorization': f"Bearer {create_access_token(1, extra={'factory_code': factory})}"}
    rows = _queue(client, headers, po['id'], department)
    assert len(rows) == 1
    assert rows[0]['received_quantity'] == rows[0]['remaining_quantity'] == 95
    with TestSessionLocal() as db:
        assert db.query(PackagingReceipt).count() == 0
        assert db.query(PackagingRecord).count() == 0
        assert db.query(Package).count() == 0
        # Simulate historical acceptance from the old screen, then a later Nastil.
        db.add(PackagingReceipt(work_order_id=work['packaging'], source_work_order_id=work['sewing'],
            production_order_id=po['id'], production_batch_id=bid, packaging_department_code=department,
            quantity=20, receive_method='manual'))
        other = ProductionBatch(production_order_id=po['id'], batch_no='LATER-02', batch_index=2, planned_quantity=30)
        db.add(other); db.flush(); other_id = other.id
        db.add(SewingRecord(work_order_id=work['sewing'], production_batch_id=other_id,
            input_qty=30, sewn_qty=30, passed_qty=30))
        db.commit()
    assert _pack(client, headers, work['packaging'], bid, 100).status_code == 400
    assert _pack(client, headers, work['packaging'], bid, 60).status_code == 201
    assert _pack(client, headers, work['packaging'], other_id, 10).status_code == 201
    rows = _queue(client, headers, po['id'], department)
    assert rows[0]['received_quantity'] == 125
    assert rows[0]['packed_quantity'] == 70
    assert rows[0]['remaining_quantity'] == 55
    with TestSessionLocal() as db:
        assert db.query(PackagingReceipt).count() == 1
        assert db.get(WorkOrder, work['packaging']).actual_input_qty == 70
        assert db.query(Package).count() == 0
    if factory != 'MIL':
        assert client.get(f"/api/work-orders/{work['packaging']}/packaging-batch-progress", headers=auth_headers).status_code == 403


def test_dedicated_factory_batch_does_not_leak_to_shared_queue(client, auth_headers):
    po, work, bid = _create(client, auth_headers)
    with TestSessionLocal() as db:
        db.get(WorkOrder, work['packaging']).status = 'ready'
        extra = ProductionBatch(production_order_id=po['id'], batch_no='ECO-02', batch_index=2, planned_quantity=80)
        db.add(extra); db.flush()
        eco = WorkOrder(production_order_id=po['id'], production_batch_id=extra.id,
            department_id=db.query(Department.id).filter_by(code='ECP').scalar(), operation='packaging',
            status='ready', planned_input_qty=80, planned_output_qty=80)
        db.add(eco); db.flush(); eco_id = eco.id
        db.add_all([SewingRecord(work_order_id=work['sewing'], production_batch_id=bid, passed_qty=40),
                    SewingRecord(work_order_id=work['sewing'], production_batch_id=extra.id, passed_qty=80)])
        db.commit()
    progress = client.get(f"/api/work-orders/{work['packaging']}/packaging-batch-progress", headers=auth_headers)
    assert progress.status_code == 200
    assert [row['id'] for row in progress.json()['items']] == [bid]
    assert _pack(client, auth_headers, work['packaging'], extra.id, 1).status_code == 409
    mil = _queue(client, auth_headers, po['id'])
    assert len(mil) == 1 and mil[0]['received_quantity'] == 40
    headers = {'Authorization': f"Bearer {create_access_token(1, extra={'factory_code': 'ECO'})}"}
    eco = _queue(client, headers, po['id'], 'ECP')
    assert len(eco) == 1 and eco[0]['work_order_id'] == eco_id and eco[0]['received_quantity'] == 80
    assert _pack(client, headers, eco_id, bid, 1).status_code == 400
    assert client.get(f"/api/work-orders/{eco_id}/packaging-batch-progress", headers=auth_headers).status_code == 403
    with TestSessionLocal() as db:
        assert db.query(PackagingRecord).count() == 0


def test_queue_read_count_does_not_grow_with_sewing_rows(client, auth_headers):
    po, work, bid = _create(client, auth_headers)
    counts = []
    for total in (1, 50):
        with TestSessionLocal() as db:
            db.query(SewingRecord).delete()
            db.add_all([SewingRecord(work_order_id=work['sewing'], production_batch_id=bid, passed_qty=1) for _ in range(total)])
            db.commit()
        selects = []
        def capture(_c, _cur, statement, _p, _ctx, _many):
            if statement.lstrip().upper().startswith('SELECT'):
                selects.append(statement)
        event.listen(test_engine, 'before_cursor_execute', capture)
        try:
            rows = _queue(client, auth_headers, po['id'])
        finally:
            event.remove(test_engine, 'before_cursor_execute', capture)
        assert rows[0]['remaining_quantity'] == total
        counts.append(len(selects))
    assert counts[0] == counts[1]
