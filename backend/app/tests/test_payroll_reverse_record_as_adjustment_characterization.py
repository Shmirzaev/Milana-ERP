from sqlalchemy import event
from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment, PayrollPeriod, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

import pytest


@pytest.mark.parametrize('with_bonus', [False, True])
def test_reversal_preserves_locked_source_and_combined_totals_and_audit(payroll_case, with_bonus):
    c = payroll_case
    def total(period_id=None):
        params = {'employee_id': c.employee_id}
        if period_id is not None:
            params['period_id'] = period_id
        r = c.client.get('/api/payroll/summary', headers=c.headers, params=params)
        assert r.status_code == 200, r.text
        return Decimal(r.json()['total_amount'])
    body = {'target_period_id': c.target_id, 'reason': 'Reversal characterization'}
    url = f'/api/payroll/records/{c.record_id}/reverse-as-adjustment'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    assert c.client.post(url, headers=c.headers, json=body).status_code == 409
    if with_bonus:
        bonus = c.client.post('/api/payroll/adjustments', headers=c.headers, json={'employee_id': c.employee_id, 'payroll_period_id': c.period_id, 'adjustment_type': 'bonus', 'amount': 500, 'reason': 'Before reversal'})
        assert bonus.status_code == 201, bonus.text
        assert total(c.period_id) == 3000
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    assert c.client.post(url, headers=c.headers, json={**body, 'target_period_id': c.period_id}).status_code == 409
    r = c.client.post(url, headers=c.headers, json=body)
    assert r.status_code == 201, r.text
    rid = r.json()['id']
    assert r.json()['source_payroll_record_id'] == c.record_id and Decimal(r.json()['signed_amount']) == -2500
    assert total(c.target_id) == -2500 and total(c.period_id) == (3000 if with_bonus else 2500)
    assert total() == (500 if with_bonus else 0)
    assert c.client.post(url, headers=c.headers, json=body).status_code == 409
    assert c.client.delete(f'/api/payroll/adjustments/{rid}', headers=c.headers).status_code == 409
    assert c.client.post(f'/api/payroll/periods/{c.target_id}/lock', headers=c.headers).status_code == 200
    for pid in [c.period_id, c.target_id]:
        refused = c.client.post('/api/payroll/adjustments', headers=c.headers, json={'employee_id': c.employee_id, 'payroll_period_id': pid, 'amount': 10, 'reason': 'Must be refused'})
        assert refused.status_code == 409, refused.text
    assert total() == (500 if with_bonus else 0)
    with c.sessions() as db:
        assert db.get(PayrollPeriod, c.period_id).status == db.get(PayrollPeriod, c.target_id).status == 'locked'
        original = db.get(PayrollRecord, c.record_id)
        assert original.status == 'recorded' and original.total_amount == 2500
        assert db.query(PayrollAdjustment).filter_by(source_payroll_record_id=c.record_id).count() == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=rid, action='create_reversal_adjustment').one()
        assert audit.new_value_json['source_payroll_record_id'] == c.record_id and audit.entry_hash


def test_reversal_commit_failure_preserves_locked_source_and_target_then_retries(payroll_case):
    c = payroll_case
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    body = {'target_period_id': c.target_id, 'reason': '  Retry reversal after failure  '}
    url = f'/api/payroll/records/{c.record_id}/reverse-as-adjustment'
    def fail_commit(session):
        raise RuntimeError('reversal characterization commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='reversal characterization commit failure'):
            c.client.post(url, headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.query(PayrollAdjustment).filter_by(source_payroll_record_id=c.record_id).count() == 0
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollAdjustment').count() == 0
        assert db.get(PayrollRecord, c.record_id).status == 'recorded'
        assert db.get(PayrollPeriod, c.period_id).status == 'locked'
    result = c.client.post(url, headers=c.headers, json=body)
    assert result.status_code == 201, result.text
    assert result.json()['reason'] == 'Retry reversal after failure'
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'employee_id': c.employee_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 0, summary.text
    with c.sessions() as db:
        assert db.query(PayrollAdjustment).filter_by(source_payroll_record_id=c.record_id).count() == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=result.json()['id'], action='create_reversal_adjustment').one()
        assert audit.entry_hash
