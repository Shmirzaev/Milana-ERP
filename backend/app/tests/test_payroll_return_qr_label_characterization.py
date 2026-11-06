from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue, scan

def test_return_voids_once_and_removes_earning_without_erasing_history(payroll_case):
    c = payroll_case
    label = issue(c.client, c.headers)
    scanned = scan(c.client, c.headers, label, {'id': c.employee_id}, scanned_at=(c.stamp + timedelta(days=1)).isoformat())
    assert scanned.status_code == 201, scanned.text
    rid = scanned.json()['record']['id']
    with c.sessions() as db:
        lid = db.query(PayrollQrLabel.id).filter_by(label_uid=label['label_uid']).scalar()
    url = f'/api/payroll/qr-labels/{lid}/return'
    assert c.client.post(url, headers=c.denied).status_code == 403
    r = c.client.post(url, headers=c.headers, params={'expected_record_id': rid})
    assert r.status_code == 200, r.text
    assert r.json()['status'] == 'available' and r.json()['return_count'] == 1
    assert c.client.post(url, headers=c.headers).status_code == 409
    total = c.client.get('/api/payroll/summary', headers=c.headers, params={'period_id': c.period_id, 'employee_id': c.employee_id})
    assert total.status_code == 200 and Decimal(total.json()['total_amount']) == 2500, total.text
    with c.sessions() as db:
        record = db.get(PayrollRecord, rid)
        assert record.status == 'voided' and record.scan_uid is None and record.original_scan_uid == label['label_uid']
        assert record.total_amount == Decimal('24.69')
        row = db.get(PayrollQrLabel, lid)
        assert row.payroll_record_id is None and row.return_count == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='return_qr').one()
        assert audit.old_value_json['payroll_record_id'] == rid and audit.entry_hash
