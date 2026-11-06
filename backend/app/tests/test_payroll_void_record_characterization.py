from decimal import Decimal

from app.schemas import AuditLog, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_void_record_removes_total_and_refuses_locked_period(payroll_case):
    c = payroll_case
    url = f'/api/payroll/records/{c.record_id}/void'
    assert c.client.post(url, headers=c.denied).status_code == 403
    r = c.client.post(url, headers=c.headers)
    assert r.status_code == 200 and r.json()['status'] == 'voided', r.text
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'period_id': c.period_id, 'employee_id': c.employee_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 0, summary.text
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    assert c.client.post(url, headers=c.headers).status_code == 409
    with c.sessions() as db:
        assert db.get(PayrollRecord, c.record_id).status == 'voided'
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=c.record_id, action='void').one()
        assert audit.old_value_json == {'status': 'recorded'} and audit.new_value_json == {'status': 'voided'} and audit.entry_hash
