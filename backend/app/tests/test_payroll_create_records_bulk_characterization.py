from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_bulk_deduplicates_and_rolls_back_invalid_batch(payroll_case):
    c = payroll_case
    uid = 'BULK-' + c.suffix
    row = {'employee_id': c.employee_id, 'scan_uid': uid, 'scanned_at': (c.stamp + timedelta(days=1)).isoformat(), 'quantity': 3, 'rate_per_piece': 2, 'operation_name': 'Bulk sewing'}
    body = {'payroll_period_id': c.period_id, 'records': [row, row]}
    url = '/api/payroll/records/bulk'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    first = c.client.post(url, headers=c.headers, json=body)
    assert first.status_code == 200, first.text
    assert (first.json()['created_count'], first.json()['duplicate_count']) == (1, 1)
    records = first.json()['records']
    assert records[0]['id'] == records[1]['id'] and Decimal(records[0]['total_amount']) == 6
    retry = c.client.post(url, headers=c.headers, json=body)
    assert retry.status_code == 200 and (retry.json()['created_count'], retry.json()['duplicate_count']) == (0, 2), retry.text
    failed_uid = 'FAILED-' + c.suffix
    failed = c.client.post(url, headers=c.headers, json={'payroll_period_id': c.period_id, 'records': [{**row, 'scan_uid': failed_uid}, {**row, 'scan_uid': failed_uid + '-BAD', 'employee_id': 99999999}]})
    assert failed.status_code == 404, failed.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=uid).count() == 1
        assert db.query(PayrollRecord).filter_by(scan_uid=failed_uid).count() == 0
        assert db.query(PayrollQrLabel).filter_by(label_uid=failed_uid).count() == 0
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=records[0]['id'], action='create').one()
        assert audit.entry_hash
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, action='bulk_create').count() == 2
