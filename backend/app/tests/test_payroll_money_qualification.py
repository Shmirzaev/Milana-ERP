from decimal import Decimal

import pytest

from app.schemas import AuditLog, PayrollAdjustment, PayrollPeriod, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401


@pytest.mark.parametrize('with_bonus', [False, True])
def test_locked_source_reversal_and_adjustment_totals_and_audit(payroll_case, with_bonus):
    c = payroll_case
    def summary(period_id=None):
        params={'employee_id':c.employee_id}
        if period_id is not None:params['period_id']=period_id
        r=c.client.get('/api/payroll/summary',headers=c.headers,params=params)
        assert r.status_code==200,r.text
        return r.json()
    if with_bonus:
        r=c.client.post('/api/payroll/adjustments',headers=c.headers,json={'employee_id':c.employee_id,'payroll_period_id':c.period_id,'adjustment_type':'bonus','amount':500,'reason':'characterized bonus'})
        assert r.status_code==201,r.text
        assert Decimal(summary(c.period_id)['total_amount'])==3000
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock',headers=c.headers).status_code==200
    assert Decimal(summary(c.period_id)['total_amount'])==(3000 if with_bonus else 2500)
    r=c.client.post(f'/api/payroll/records/{c.record_id}/reverse-as-adjustment',headers=c.headers,json={'target_period_id':c.target_id,'reason':'characterized reversal'})
    assert r.status_code==201,r.text
    rid=r.json()['id']
    assert Decimal(summary(c.target_id)['total_amount'])==-2500
    assert Decimal(summary(c.period_id)['total_amount'])==(3000 if with_bonus else 2500)
    assert Decimal(summary()['total_amount'])==(500 if with_bonus else 0)
    assert c.client.post(f'/api/payroll/periods/{c.target_id}/lock',headers=c.headers).status_code==200
    for pid in [c.period_id,c.target_id]:
        denied=c.client.post('/api/payroll/adjustments',headers=c.headers,json={'employee_id':c.employee_id,'payroll_period_id':pid,'adjustment_type':'bonus','amount':10,'reason':'must be refused'})
        assert denied.status_code==409,denied.text
    retry=c.client.post(f'/api/payroll/records/{c.record_id}/reverse-as-adjustment',headers=c.headers,json={'target_period_id':c.target_id,'reason':'duplicate reversal'})
    assert retry.status_code==409,retry.text
    with c.sessions() as db:
        assert db.get(PayrollPeriod,c.period_id).status=='locked'
        assert db.get(PayrollRecord,c.record_id).status=='recorded'
        assert db.query(PayrollAdjustment).filter_by(source_payroll_record_id=c.record_id).count()==1
        audit=db.query(AuditLog).filter_by(entity_type='PayrollAdjustment',entity_id=rid).one()
        assert audit.action=='create_reversal_adjustment' and audit.entry_hash
        assert audit.new_value_json['source_payroll_record_id']==c.record_id
        if with_bonus:
            bonus=db.query(PayrollAdjustment).filter_by(employee_id=c.employee_id,adjustment_type='bonus').one()
            assert db.query(AuditLog).filter_by(entity_type='PayrollAdjustment',entity_id=bonus.id,action='create').count()==1
