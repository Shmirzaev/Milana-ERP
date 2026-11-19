from sqlalchemy import event
import pytest
from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_adjustments_change_total_and_locked_period_refuses_further_writes(payroll_case):
    c = payroll_case
    url = '/api/payroll/adjustments'
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id, 'amount': 500, 'adjustment_type': 'bonus', 'currency': 'uzs', 'reason': 'Bonus characterization'}
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    bonus = c.client.post(url, headers=c.headers, json=body)
    assert bonus.status_code == 201 and Decimal(bonus.json()['signed_amount']) == 500 and bonus.json()['currency'] == 'UZS', bonus.text
    deduction = c.client.post(url, headers=c.headers, json={**body, 'amount': -200, 'adjustment_type': None, 'reason': 'Deduction characterization'})
    assert deduction.status_code == 201 and deduction.json()['adjustment_type'] == 'deduction' and Decimal(deduction.json()['signed_amount']) == -200, deduction.text
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'period_id': c.period_id, 'employee_id': c.employee_id})
    assert summary.status_code == 200, summary.text
    assert Decimal(summary.json()['piecework_amount']) == 2500 and Decimal(summary.json()['adjustment_amount']) == 300 and Decimal(summary.json()['total_amount']) == 2800
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    assert c.client.post(url, headers=c.headers, json=body).status_code == 409
    with c.sessions() as db:
        assert db.query(PayrollAdjustment).filter_by(employee_id=c.employee_id).count() == 2
        for row in [bonus.json(), deduction.json()]:
            audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=row['id'], action='create').one()
            assert audit.entry_hash


def test_create_adjustment_commit_failure_rolls_back_audit_and_total_then_retries(payroll_case):
    c = payroll_case
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id,
            'amount': 500, 'adjustment_type': 'bonus', 'reason': 'Rollback bonus'}
    def fail_commit(session):
        raise RuntimeError('adjustment characterization commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='adjustment characterization commit failure'):
            c.client.post('/api/payroll/adjustments', headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.query(PayrollAdjustment).filter_by(employee_id=c.employee_id).count() == 0
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollAdjustment').count() == 0
    result = c.client.post('/api/payroll/adjustments', headers=c.headers, json=body)
    assert result.status_code == 201, result.text
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'employee_id': c.employee_id, 'period_id': c.period_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 3000, summary.text
    with c.sessions() as db:
        audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=result.json()['id'], action='create').one()
        assert audit.entry_hash
