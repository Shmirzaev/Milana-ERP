from app.schemas import AuditLog, PayrollPeriod, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def test_lock_preserves_records_and_appends_audit_and_refuses_finalized(payroll_case):
    c=payroll_case
    url=f'/api/payroll/periods/{c.period_id}/lock'
    assert c.client.post(url,headers=c.denied).status_code==403
    r=c.client.post(url,headers=c.headers)
    assert r.status_code==200 and r.json()['status']=='locked',r.text
    with c.sessions() as db:
        assert db.get(PayrollPeriod,c.period_id).status=='locked'
        assert db.get(PayrollRecord,c.record_id).status=='recorded'
        audit=db.query(AuditLog).filter_by(entity_type='PayrollPeriod',entity_id=c.period_id,action='lock').one()
        assert audit.old_value_json=={'status':'open'} and audit.new_value_json=={'status':'locked'} and audit.entry_hash
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/approve',headers=c.headers).status_code==200
    assert c.client.post(url,headers=c.headers).status_code==409
