from app.schemas import AuditLog, PayrollPeriod, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def test_approval_requires_lock_and_persists_actor_records_and_audit(payroll_case):
    c=payroll_case
    url=f'/api/payroll/periods/{c.period_id}/approve'
    assert c.client.post(url,headers=c.denied).status_code==403
    assert c.client.post(url,headers=c.headers).status_code==409
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock',headers=c.headers).status_code==200
    r=c.client.post(url,headers=c.headers)
    assert r.status_code==200 and r.json()['status']=='approved',r.text
    assert c.client.post(url,headers=c.headers).status_code==409
    with c.sessions() as db:
        period=db.get(PayrollPeriod,c.period_id)
        assert period.approved_by==c.actor_id and period.approved_at is not None
        assert db.get(PayrollRecord,c.record_id).status=='approved'
        audit=db.query(AuditLog).filter_by(entity_type='PayrollPeriod',entity_id=c.period_id,action='approve').one()
        assert audit.old_value_json=={'status':'locked'} and audit.new_value_json=={'status':'approved'} and audit.entry_hash
