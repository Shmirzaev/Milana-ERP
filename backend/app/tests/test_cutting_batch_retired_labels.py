from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import (
    AuditLog, Bundle, CuttingRecord, Employee, PayrollQrLabel, PayrollRecord,
    ProductionBatch, StockBatch, WorkOrder,
)
from app.tests.test_cutting_batch_lifecycle import _cut
from app.tests.test_passport_cutting_submission import passport_cutting  # noqa: F401


def _snapshot(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def _case(client, headers, fixture):
    stocks, order, work, payload = fixture
    _cut(client, headers, payload)
    with SessionLocal() as db:
        empty = ProductionBatch(production_order_id=order['id'], batch_no='EMPTY-02',
                                batch_index=2, planned_quantity=600, name='Nastil 2')
        db.add(empty)
        db.commit()
        empty_id = empty.id
    return stocks, order, work, payload, empty_id


def _label(order, **kwargs):
    return PayrollQrLabel(production_order_id=order['id'], label_uid=uuid4().hex,
                          status='superseded', superseded_at=datetime.now(timezone.utc), **kwargs)


def test_empty_sibling_delete_keeps_cutting_labels_and_existing_audit(client, auth_headers, passport_cutting):
    stocks, order, work, payload, empty_id = _case(client, auth_headers, passport_cutting)
    with SessionLocal() as db:
        # Match the incident's 600-piece Nastil and 216 retired order-level labels.
        record = db.query(CuttingRecord).filter_by(work_order_id=work['id']).one()
        record.cut_pieces = record.passed_pieces = 600
        record.total_bundled_quantity = 600
        bundle = db.query(Bundle).filter_by(cutting_record_id=record.id).one()
        bundle.quantity = 600
        keep = db.get(ProductionBatch, payload['production_batch_id'])
        keep.planned_quantity = 600
        cutting = db.get(WorkOrder, work['id'])
        cutting.actual_input_qty = cutting.actual_output_qty = cutting.passed_qty = 600
        cutting.planned_input_qty = cutting.planned_output_qty = 600
        db.add_all([_label(order) for _ in range(216)])
        db.commit()
        record_before, bundle_before, batch_before = map(_snapshot, (record, bundle, keep))
        labels_before = {r.id: _snapshot(r) for r in db.query(PayrollQrLabel).filter_by(production_order_id=order['id'])}
        audits_before = {r.id: _snapshot(r) for r in db.query(AuditLog)}
        stock_before = {r['id']: _snapshot(db.get(StockBatch, r['id'])) for r in stocks}
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{empty_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()['deleted_bundle_count'] == 0
    with SessionLocal() as db:
        assert db.get(ProductionBatch, empty_id) is None
        assert _snapshot(db.get(ProductionBatch, batch_before['id'])) == batch_before
        assert _snapshot(db.get(CuttingRecord, record_before['id'])) == record_before
        assert _snapshot(db.get(Bundle, bundle_before['id'])) == bundle_before
        assert db.get(WorkOrder, work['id']).passed_qty == 600
        assert {r.id: _snapshot(r) for r in db.query(PayrollQrLabel).filter_by(production_order_id=order['id'])} == labels_before
        assert {key: _snapshot(db.get(StockBatch, key)) for key in stock_before} == stock_before
        assert all(_snapshot(db.get(AuditLog, key)) == value for key, value in audits_before.items())
        audit = db.query(AuditLog).filter_by(action='delete_cutting_batch', entity_id=empty_id).one()
        assert audit.old_value_json['batch']['batch_no'] == 'EMPTY-02'
        assert audit.old_value_json['records'] == []


@pytest.mark.parametrize('evidence', [
    'available', 'scanned', 'closed', 'last_scanned_at', 'returned_at', 'returned_by',
    'return_count', 'payroll_record_id', 'scan_uid', 'original_scan_uid', 'split_parent', 'split_child',
])
def test_unallocated_used_or_active_label_still_blocks(client, auth_headers, passport_cutting, evidence):
    _, order, work, _, empty_id = _case(client, auth_headers, passport_cutting)
    with SessionLocal() as db:
        label = _label(order)
        db.add(label)
        db.flush()
        if evidence in {'available', 'scanned', 'closed'}:
            label.status = evidence
        elif evidence in {'last_scanned_at', 'returned_at'}:
            setattr(label, evidence, datetime.now(timezone.utc))
        elif evidence == 'returned_by':
            from app.models import User
            label.returned_by = db.query(User.id).first()[0]
        elif evidence == 'return_count':
            label.return_count = 1
        elif evidence.startswith('split_'):
            other = _label(order, production_batch_id=passport_cutting[3]['production_batch_id'])
            db.add(other)
            db.flush()
            if evidence == 'split_parent':
                label.split_from_label_id = other.id
            else:
                other.split_from_label_id = label.id
        else:
            employee = Employee(full_name='Retired label history test')
            db.add(employee)
            db.flush()
            payroll = PayrollRecord(employee_id=employee.id, dedupe_key=uuid4().hex,
                                    production_order_id=order['id'],
                                    production_batch_id=passport_cutting[3]['production_batch_id'],
                                    scanned_at=datetime.now(timezone.utc), quantity=1,
                                    rate_per_piece=1, total_amount=1)
            db.add(payroll)
            db.flush()
            if evidence == 'payroll_record_id':
                label.payroll_record_id = payroll.id
            else:
                setattr(payroll, evidence, label.label_uid)
        db.commit()
        db.refresh(label)
        before = _snapshot(label)
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{empty_id}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert 'Unallocated downstream history' in response.text
    with SessionLocal() as db:
        assert db.get(ProductionBatch, empty_id)
        assert _snapshot(db.get(PayrollQrLabel, before['id'])) == before
        assert not db.query(AuditLog).filter_by(action='delete_cutting_batch', entity_id=empty_id).count()


def test_retired_label_linked_to_selected_batch_is_not_bypassed(client, auth_headers, passport_cutting):
    _, order, work, _, empty_id = _case(client, auth_headers, passport_cutting)
    with SessionLocal() as db:
        db.add(_label(order, production_batch_id=empty_id))
        db.commit()
    response = client.delete(f"/api/work-orders/{work['id']}/batches/{empty_id}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert 'linked production, payroll or packaging history' in response.text
