from app.schemas import AuditLog, PayrollPeriod
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


def test_update_period_metadata_overlap_and_audit(payroll_case):
    c = payroll_case
    url=f'/api/payroll/periods/{c.period_id}'
    r=c.client.patch(url,headers=c.headers,json={'name':'Updated payroll','notes':'retained notes'})
    assert r.status_code==200,r.text
    assert r.json()['name']=='Updated payroll'
    assert c.client.patch(url,headers=c.headers,json={'status':'approved'}).status_code==409
    assert c.client.patch(url,headers=c.denied,json={'name':'forbidden'}).status_code==403
    with c.sessions() as db:
        row=db.get(PayrollPeriod,c.period_id)
        assert (row.name,row.notes,row.status)==('Updated payroll','retained notes','open')
        audit=db.query(AuditLog).filter_by(entity_type='PayrollPeriod',entity_id=c.period_id,action='update').one()
        assert audit.new_value_json=={'name':'Updated payroll','notes':'retained notes'} and audit.entry_hash
