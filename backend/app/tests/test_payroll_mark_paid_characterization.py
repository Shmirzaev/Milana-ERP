from app.schemas import AuditLog, PayrollPeriod, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def test_payment_requires_approval_and_atomically_pays_records(payroll_case):
    c=payroll_case
    url=f'/api/payroll/periods/{c.period_id}/mark-paid'
    assert c.client.post(url,headers=c.denied).status_code==403
    assert c.client.post(url,headers=c.headers).status_code==409
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock',headers=c.headers).status_code==200
    assert c.client.post(url,headers=c.headers).status_code==409
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/approve',headers=c.headers).status_code==200
    r=c.client.post(url,headers=c.headers)
    assert r.status_code==200 and r.json()['status']=='paid',r.text
    assert c.client.post(url,headers=c.headers).status_code==409
    with c.sessions() as db:
        assert db.get(PayrollPeriod,c.period_id).status=='paid'
        assert db.get(PayrollRecord,c.record_id).status=='paid'
        assert db.get(PayrollPeriod,c.target_id).status=='open'
        audit=db.query(AuditLog).filter_by(entity_type='PayrollPeriod',entity_id=c.period_id,action='mark_paid').one()
        assert audit.new_value_json=={'status':'paid'} and audit.entry_hash
