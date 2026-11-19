from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue

def test_numeric_scan_uses_issued_pay_and_replays_one_earning(payroll_case):
    c = payroll_case
    label = issue(c.client, c.headers)
    body = {'token': label['qr_token'], 'employee_id': c.employee_id, 'scanned_at': (c.stamp + timedelta(days=1)).isoformat()}
    url = '/api/payroll/scan/numeric-work'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    assert c.client.post(url, headers=c.headers, json={**body, 'token': 'invalid'}).status_code == 400
    first = c.client.post(url, headers=c.headers, json=body)
    assert first.status_code == 201, first.text
    record = first.json()['record']
    assert Decimal(record['total_amount']) == Decimal('24.69') and record['employee_id'] == c.employee_id
    retry = c.client.post(url, headers=c.headers, json=body)
    assert retry.status_code == 201 and retry.json()['record']['id'] == record['id'] and retry.json()['record']['duplicate'] is True, retry.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=label['label_uid']).count() == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=record['id'], action='create').one()
        assert audit.entry_hash
        assert db.query(PayrollQrLabel).filter_by(label_uid=label['label_uid']).one().payroll_record_id == record['id']
