"""Bundle receipt and manual output describe the same Sewing input."""
from uuid import uuid4

import pytest

from app.models import AuditLog, Bundle, BundleScanLog, CuttingRecord, ProductionBatch, ProductionOrder, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_production_flow import _factory_headers
from app.tests.test_sewing_actual_output import sew
from app.tests.test_sewing_cutting_output_guard import setup_order


def received_order(client, factory, batched, *, receive=True, batch_work_order=False):
    batch, orders = setup_order(factory, batched, cut=600)
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        if batch_work_order:
            for wid in orders.values():
                db.get(WorkOrder, wid).production_batch_id = batch
        po = db.get(ProductionOrder, wo.production_order_id)
        bundles = [Bundle(bundle_no=f'RECEIPT-{uuid4().hex}', barcode=uuid4().hex,
            production_order_id=po.id, production_batch_id=batch, model_id=po.model_id,
            color='white', size='M', quantity=100, status='sent_to_sewing', sewing_factory_code=factory)
            for _ in range(6)]
        db.add_all(bundles); db.commit()
        ids = [b.id for b in bundles]
    headers = _factory_headers(factory)
    if receive:
        for bid in ids:
            response = client.post(f'/api/bundles/{bid}/receive-sewing', headers=headers)
            assert response.status_code == 200, response.text
    return batch, orders, ids, headers


@pytest.mark.parametrize('factory', ['MIL', 'BST', 'ECO'])
@pytest.mark.parametrize('batched,batch_work_order', [(False, False), (True, False), (True, True)])
def test_received_600_allows_495_then_105_without_duplicate_credit(client, factory, batched, batch_work_order):
    batch, orders, ids, headers = received_order(client, factory, batched, batch_work_order=batch_work_order)
    with TestSessionLocal() as db:
        before = [(b.id, b.barcode, b.quantity, b.status) for b in db.query(Bundle).filter(Bundle.id.in_(ids)).order_by(Bundle.id)]
        scans = db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(ids)).count()
        assert db.get(WorkOrder, orders['sewing']).actual_input_qty == 600
        assert db.query(SewingRecord).filter_by(work_order_id=orders['sewing']).count() == 0
    first = sew(client, headers, batch, orders, 495, 495)
    assert first.status_code == 201, first.text
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        assert (wo.actual_input_qty, wo.passed_qty) == (600, 495)
        audit = db.query(AuditLog).filter_by(entity_type='SewingRecord', entity_id=first.json()['id'], action='create').one()
        assert audit.new_value_json['input_qty'] == 495
        assert audit.new_value_json['passed_qty'] == 495
    assert sew(client, headers, batch, orders, 105, 105).status_code == 201
    assert sew(client, headers, batch, orders, 1, 0).status_code == 400
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        assert (wo.actual_input_qty, wo.passed_qty) == (600, 600)
        assert [(b.id, b.barcode, b.quantity, b.status) for b in db.query(Bundle).filter(Bundle.id.in_(ids)).order_by(Bundle.id)] == before
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(ids)).count() == scans
    ready = client.get('/api/packaging/receive-options', headers=headers)
    assert ready.status_code == 200, ready.text
    assert any(r['source_work_order_id'] == orders['sewing'] and r['available_quantity'] == 600 for r in ready.json())


@pytest.mark.parametrize('batched', [False, True])
def test_correction_and_delete_preserve_received_input(client, batched):
    batch, orders, _, headers = received_order(client, 'MIL', batched)
    first = sew(client, headers, batch, orders, 400, 300)
    assert first.status_code == 201, first.text
    rid = first.json()['id']
    changed = client.patch(f'/api/sewing/records/{rid}', headers=headers, json={
        'expected_version': 0, 'input_qty': 495, 'sewn_qty': 495, 'passed_qty': 495})
    assert changed.status_code == 200, changed.text
    blocked = client.patch(f'/api/sewing/records/{rid}', headers=headers, json={
        'expected_version': 1, 'input_qty': 601, 'sewn_qty': 495, 'passed_qty': 495})
    assert blocked.status_code == 409, blocked.text
    removed = client.request('DELETE', f'/api/sewing/records/{rid}', headers=headers, json={'expected_version': 1})
    assert removed.status_code == 200, removed.text
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        assert (wo.actual_input_qty, wo.passed_qty) == (600, 0)
        assert db.query(AuditLog).filter_by(entity_type='SewingRecord', entity_id=rid).count() == 3
    assert sew(client, headers, batch, orders, 495, 495).status_code == 201


@pytest.mark.parametrize('batched', [False, True])
def test_receiving_after_output_does_not_add_input_twice(client, batched):
    batch, orders, ids, headers = received_order(client, 'MIL', batched, receive=False)
    # Output may be recorded before the physical bundles are scanned.
    with TestSessionLocal() as db:
        db.get(WorkOrder, orders['sewing']).status = 'in_progress'
        db.commit()
    assert sew(client, headers, batch, orders, 495, 495).status_code == 201
    for bid in ids:
        assert client.post(f'/api/bundles/{bid}/receive-sewing', headers=headers).status_code == 200
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, orders['sewing']).actual_input_qty == 600
    assert sew(client, headers, batch, orders, 105, 105).status_code == 201


@pytest.mark.parametrize('batched', [False, True])
def test_old_double_counted_display_counter_does_not_block_new_work(client, batched):
    batch, orders, _, headers = received_order(client, 'MIL', batched)
    assert sew(client, headers, batch, orders, 495, 300).status_code == 201
    with TestSessionLocal() as db:
        db.get(WorkOrder, orders['sewing']).actual_input_qty = 1095
        db.commit()
    assert sew(client, headers, batch, orders, 105, 105).status_code == 201
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, orders['sewing']).actual_input_qty == 600
        assert [r.input_qty for r in db.query(SewingRecord).filter_by(work_order_id=orders['sewing']).order_by(SewingRecord.id)] == [495, 105]


def test_shared_work_order_deduplicates_each_nastil_separately(client):
    batch, orders, _, headers = received_order(client, 'MIL', True)
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, orders['sewing'])
        other = ProductionBatch(production_order_id=wo.production_order_id, batch_index=2,
            batch_no=f'{wo.production_order_id:04d}-02', planned_quantity=400)
        db.add(other); db.flush()
        db.add(CuttingRecord(work_order_id=orders['cutting'], production_batch_id=other.id,
            cut_pieces=400, passed_pieces=400))
        db.get(WorkOrder, orders['cutting']).passed_qty = 1000
        db.commit(); other_id = other.id
    assert sew(client, headers, batch, orders, 495, 495).status_code == 201
    assert sew(client, headers, other_id, orders, 400, 400).status_code == 201
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, orders['sewing']).actual_input_qty == 1000
