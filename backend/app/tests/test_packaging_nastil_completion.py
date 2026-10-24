"""Closing one nastil must not consume a sibling's packaging quantity."""
import pytest

from app.models import ProductionBatch, SewingRecord, WorkOrder
from app.models.workflow_service import processed_work_order_qty
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_sewing_output import _create, _pack


def setup_nastils(client, headers):
    po, work, first = _create(client, headers)
    with TestSessionLocal() as db:
        db.get(ProductionBatch, first).planned_quantity = 300
        second = ProductionBatch(production_order_id=po['id'], batch_no='NASTIL-2',
                                 batch_index=2, name='Nastil 2', planned_quantity=300)
        db.add(second)
        db.flush()
        for operation in ('cutting', 'sewing'):
            wo = db.get(WorkOrder, work[operation])
            wo.status = 'completed'
            wo.actual_output_qty = wo.passed_qty = 600
        # Historical shortage accepted after one cut, followed by the next cut.
        db.get(WorkOrder, work['cutting']).failed_qty = 300
        for bid in (first, second.id):
            db.add(SewingRecord(work_order_id=work['sewing'], production_batch_id=bid,
                                input_qty=300, sewn_qty=300, passed_qty=300))
        db.get(WorkOrder, work['packaging']).status = 'in_progress'
        db.commit()
        return po, work, first, second.id


def test_two_nastils_stay_accessible_until_all_packaging_is_accounted_for(client, auth_headers):
    _, work, first, second = setup_nastils(client, auth_headers)
    wid = work['packaging']
    assert _pack(client, auth_headers, wid, first, 300).status_code == 201
    detail = client.get(f'/api/work-orders/{wid}', headers=auth_headers).json()
    assert detail['status'] == 'in_progress'
    assert detail['passed_qty'] == 300
    refused = client.post(f'/api/work-orders/{wid}/complete', headers=auth_headers)
    assert refused.status_code == 409, refused.text
    progress = client.get(f'/api/work-orders/{wid}/packaging-batch-progress', headers=auth_headers).json()
    assert next(r for r in progress['items'] if r['id'] == second)['available_input_qty'] == 300
    assert _pack(client, auth_headers, wid, first, 1).status_code == 400
    assert _pack(client, auth_headers, wid, second, 280).status_code == 201
    assert client.get(f'/api/work-orders/{wid}', headers=auth_headers).json()['status'] == 'in_progress'
    assert _pack(client, auth_headers, wid, second, 20).status_code == 201
    assert client.get(f'/api/work-orders/{wid}', headers=auth_headers).json()['status'] == 'completed'
    assert client.post(f'/api/work-orders/{wid}/complete', headers=auth_headers).status_code == 200


def test_record_on_historically_completed_packaging_restores_in_progress(client, auth_headers):
    _, work, first, _ = setup_nastils(client, auth_headers)
    with TestSessionLocal() as db:
        db.get(WorkOrder, work['packaging']).status = 'completed'
        db.commit()
    assert _pack(client, auth_headers, work['packaging'], first, 100).status_code == 201
    detail = client.get(f"/api/work-orders/{work['packaging']}", headers=auth_headers).json()
    assert detail['status'] == 'in_progress'
    assert detail['end_time'] is None


@pytest.mark.parametrize('cut_passed,cut_failed,sew_failed,packed,damaged,expected', [
    (600, 300, 0, 300, 0, 300),  # fulfilled historical shortage
    (500, 300, 0, 300, 0, 400),  # only 100 shortage pieces still exist
    (300, 300, 0, 300, 0, 600),  # genuine accepted shortage
    (590, 10, 5, 582, 3, 600),  # genuine defects in multiple stages
])
def test_completion_counts_only_remaining_losses(client, auth_headers, cut_passed, cut_failed,
                                                sew_failed, packed, damaged, expected):
    _, work, _ = _create(client, auth_headers, batched=False)
    with TestSessionLocal() as db:
        cut = db.get(WorkOrder, work['cutting'])
        cut.passed_qty, cut.failed_qty = cut_passed, cut_failed
        sew = db.get(WorkOrder, work['sewing'])
        sew.passed_qty, sew.failed_qty = cut_passed - sew_failed, sew_failed
        pkg = db.get(WorkOrder, work['packaging'])
        pkg.passed_qty, pkg.failed_qty = packed, damaged
        db.flush()
        assert processed_work_order_qty(db, pkg) == expected
