import pytest
from sqlalchemy import event

from decimal import Decimal
from datetime import timedelta

from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401

def test_create_record_manual_pay_and_duplicate_after_lock(payroll_case):
    c = payroll_case
    uid = 'RECORD-' + c.suffix
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id, 'scan_uid': uid, 'scanned_at': (c.stamp + timedelta(days=1)).isoformat(), 'quantity': 2, 'rate_per_piece': '3.50', 'operation_name': 'Manual sewing'}
    url = '/api/payroll/records'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    first = c.client.post(url, headers=c.headers, json=body)
    assert first.status_code == 201, first.text
    rid = first.json()['id']
    assert Decimal(first.json()['total_amount']) == 7 and first.json()['duplicate'] is False
    assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    retry = c.client.post(url, headers=c.headers, json=body)
    assert retry.status_code == 201 and retry.json()['id'] == rid and retry.json()['duplicate'] is True, retry.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=uid).count() == 1
        row = db.get(PayrollRecord, rid)
        assert row.payroll_period_id == c.period_id and row.total_amount == 7
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).one().payroll_record_id == rid
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=rid, action='create').one()
        assert audit.entry_hash


def test_create_record_rollback_removes_qr_record_audit_then_retries(payroll_case):
    c = payroll_case
    uid = 'ROLLBACK-' + c.suffix
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id,
            'scan_uid': uid, 'scanned_at': (c.stamp + timedelta(days=1)).isoformat(),
            'quantity': 2, 'rate_per_piece': '3.50', 'operation_name': 'Rollback sewing'}
    def fail_commit(session):
        if any(isinstance(row, PayrollRecord) and row.scan_uid == uid for row in session.identity_map.values()):
            raise RuntimeError('record characterization commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='record characterization commit failure'):
            c.client.post('/api/payroll/records', headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=uid).count() == 0
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 0
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollRecord').count() == 0
    result = c.client.post('/api/payroll/records', headers=c.headers, json=body)
    assert result.status_code == 201, result.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=uid).count() == 1
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 1
        audit = db.query(AuditLog).filter_by(entity_type='PayrollRecord', entity_id=result.json()['id']).one()
        assert audit.entry_hash


@pytest.mark.parametrize('invalid', ['employee', 'control', 'snapshot', 'work_date'])
def test_create_record_refusals_preserve_payroll_rows_and_audit(payroll_case, invalid):
    c = payroll_case
    uid = 'REFUSED-' + c.suffix
    body = {'employee_id': c.employee_id, 'payroll_period_id': c.period_id,
            'scan_uid': uid, 'scanned_at': (c.stamp + timedelta(days=1)).isoformat(),
            'quantity': 2, 'rate_per_piece': '3.50', 'operation_name': 'Refused sewing'}
    expected = 409
    if invalid == 'employee':
        body['employee_id'] = 99999999
        expected = 404
    elif invalid == 'control':
        body['operation_name'] = 'Kontrol'
    elif invalid == 'snapshot':
        body['employee'] = {'oversized': 'x' * 17000}
        expected = 422
    else:
        body['work_date'] = (c.stamp + timedelta(days=1)).date().isoformat()
        assert c.client.post(f'/api/payroll/periods/{c.period_id}/lock', headers=c.headers).status_code == 200
    result = c.client.post('/api/payroll/records', headers=c.headers, json=body)
    assert result.status_code == expected, result.text
    with c.sessions() as db:
        assert db.query(PayrollRecord).filter_by(scan_uid=uid).count() == 0
        assert db.query(PayrollQrLabel).filter_by(label_uid=uid).count() == 0
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, entity_type='PayrollRecord').count() == 0
