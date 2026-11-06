from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue, scan

def test_split_scanned_record_preserves_rounded_total_and_replay(payroll_case):
    c = payroll_case
    label = issue(c.client, c.headers)
    scanned = scan(c.client, c.headers, label, {'id': c.employee_id}, scanned_at=(c.stamp + timedelta(days=1)).isoformat())
    assert scanned.status_code == 201, scanned.text
    original = scanned.json()['record']
    body = {'parts': [{'employee_id': c.employee_id, 'quantity': 7}, {'employee_id': c.employee_id, 'quantity': 13}]}
    url = f"/api/payroll/records/{original['id']}/split"
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    bad = {'parts': [{'employee_id': c.employee_id, 'quantity': 7}, {'employee_id': c.employee_id, 'quantity': 12}]}
    assert c.client.post(url, headers=c.headers, json=bad).status_code == 409
    r = c.client.post(url, headers=c.headers, json=body)
    assert r.status_code == 200, r.text
    children = r.json()
    assert sum(Decimal(row['total_amount']) for row in children) == Decimal(original['total_amount'])
    assert [Decimal(row['quantity']) for row in children] == [7, 13]
    assert all(row['payroll_period_id'] == c.period_id and row['scanned_at'] == original['scanned_at'] for row in children)
    retry = c.client.post(url, headers=c.headers, json=body)
    assert retry.status_code == 200 and [row['id'] for row in retry.json()] == [row['id'] for row in children], retry.text
    assert c.client.post(url, headers=c.headers, json=bad).status_code == 409
    with c.sessions() as db:
        assert db.get(PayrollRecord, original['id']).status == 'voided'
        parent = db.query(PayrollQrLabel).filter_by(label_uid=label['label_uid']).one()
        assert parent.status == 'superseded' and parent.payroll_record_id == original['id']
        assert db.query(PayrollQrLabel).filter_by(split_from_label_id=parent.id).count() == 2
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=original['id'], action='split_scanned_qr').one()
        assert audit.entry_hash
