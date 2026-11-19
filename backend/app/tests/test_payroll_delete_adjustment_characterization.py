from sqlalchemy import event
import pytest
from decimal import Decimal

from app.schemas import AuditLog, PayrollAdjustment
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_delete_adjustment_recalculates_and_cannot_modify_locked_period(payroll_case):
    c = payroll_case
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id, 'amount': 500, 'adjustment_type': 'bonus', 'reason': 'Delete characterization'}
    created = c.client.post('/api/payroll/adjustments', headers=c.headers, json=body)
    assert created.status_code == 201, created.text
    aid = created.json()['id']
    url = f'/api/payroll/adjustments/{aid}'
    assert c.client.delete(url, headers=c.denied).status_code == 403
    assert c.client.delete(url, headers=c.headers).status_code == 204
    assert c.client.delete(url, headers=c.headers).status_code == 404
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'period_id': c.period_id, 'employee_id': c.employee_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 2500, summary.text
    with c.sessions() as db:
        assert db.get(PayrollAdjustment, aid) is None
    other = c.client.post('/api/payroll/adjustments', headers=c.headers, json={**body, 'amount': 200})
    assert other.status_code == 201, other.text
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    assert c.client.delete(f"/api/payroll/adjustments/{other.json()['id']}", headers=c.headers).status_code == 409
    with c.sessions() as db:
        assert db.get(PayrollAdjustment, other.json()['id']).amount == Decimal('200')
        audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=aid, action='delete').one()
        assert audit.old_value_json['amount'] == 500 and audit.entry_hash


def test_delete_adjustment_commit_failure_preserves_row_total_and_audit_then_retries(payroll_case):
    c = payroll_case
    created = c.client.post('/api/payroll/adjustments', headers=c.headers, json={
        'employee_id': c.employee_id, 'payroll_period_id': c.period_id,
        'amount': 500, 'adjustment_type': 'bonus', 'reason': 'Delete rollback bonus'})
    assert created.status_code == 201, created.text
    aid = created.json()['id']
    url = f'/api/payroll/adjustments/{aid}'
    with c.sessions() as db:
        before_audits = db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollAdjustment').count()
    def fail_commit(session):
        raise RuntimeError('delete characterization commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='delete characterization commit failure'):
            c.client.delete(url, headers=c.headers)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.get(PayrollAdjustment, aid).amount == Decimal('500')
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollAdjustment').count() == before_audits
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'employee_id': c.employee_id, 'period_id': c.period_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 3000, summary.text
    assert c.client.delete(url, headers=c.headers).status_code == 204
    summary = c.client.get('/api/payroll/summary', headers=c.headers, params={'employee_id': c.employee_id, 'period_id': c.period_id})
    assert summary.status_code == 200 and Decimal(summary.json()['total_amount']) == 2500, summary.text
    with c.sessions() as db:
        assert db.get(PayrollAdjustment, aid) is None
        audit = db.query(AuditLog).filter_by(entity_type='PayrollAdjustment', entity_id=aid, action='delete').one()
        assert audit.entry_hash
