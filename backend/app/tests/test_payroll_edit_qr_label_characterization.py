from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.routes.payroll import router
from app.core.deps import DbSession, require_permissions
from app.libs.dto.people.payroll import PayrollQrLabelEditIn, PayrollQrLabelOut
from app.models.people import payroll_qr_service
from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord, User
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue, scan


@pytest.fixture
def edit_case(payroll_case):
    c = payroll_case
    if not hasattr(payroll_qr_service, 'edit_qr_label'):
        yield c
        return
    app = FastAPI()
    calls = []

    @app.patch('/api/payroll/qr-labels/{label_id}', response_model=PayrollQrLabelOut)
    def candidate_edit(
        label_id: int, payload: PayrollQrLabelEditIn, db: DbSession,
        current: User = Depends(require_permissions('payroll.manage', '*')),
    ):
        calls.append(label_id)
        return payroll_qr_service.edit_qr_label(label_id, payload, db, current)

    # A direct route precedes the lazy included router, and every candidate test
    # must prove that it reached the new service rather than the legacy handler.
    app.include_router(router, prefix='/api')
    app.dependency_overrides.update(c.client.app.dependency_overrides)
    with TestClient(app) as client:
        c.client = client
        yield c
    assert calls, 'Candidate edit service was never invoked'


def _issued(c):
    label = issue(c.client, c.headers)
    with c.sessions() as db:
        row = db.query(PayrollQrLabel).filter_by(label_uid=label['label_uid']).one()
        row.payload = 'original printed snapshot'
        db.commit()
        return label, row.id


def test_edit_retains_qr_identity_and_refuses_scanned_history(edit_case):
    c = edit_case
    label, lid = _issued(c)
    url = f'/api/payroll/qr-labels/{lid}'
    body = {'operation_name': ' Corrected sewing ', 'rate_per_piece': '2.5000'}
    assert c.client.patch(url, headers=c.denied, json=body).status_code == 403
    result = c.client.patch(url, headers=c.headers, json=body)
    assert result.status_code == 200, result.text
    assert (result.json()['label_uid'], result.json()['qr_token']) == (label['label_uid'], label['qr_token'])
    assert result.json()['operation_name'] == 'Corrected sewing'
    assert Decimal(result.json()['rate_per_piece']) == Decimal('2.5')
    assert result.json()['payload'] is None
    scanned = scan(c.client, c.headers, label, {'id': c.employee_id}, scanned_at=(c.stamp + timedelta(days=1)).isoformat())
    assert scanned.status_code == 201, scanned.text
    assert c.client.patch(url, headers=c.headers, json=body).status_code == 409
    with c.sessions() as db:
        row = db.get(PayrollQrLabel, lid)
        assert row.operation_name == 'Corrected sewing' and row.status == 'scanned'
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='edit_unscanned_qr').one()
        assert audit.old_value_json['operation_name'] == 'Sew' and audit.entry_hash
        assert audit.new_value_json['qr_token'] == label['qr_token']


def test_edit_reference_validation_and_name_rate_error_order(edit_case):
    c = edit_case
    _, lid = _issued(c)
    body = {'operation_name': ' ', 'rate_per_piece': 1}
    missing = c.client.patch('/api/payroll/qr-labels/99999999', headers=c.headers, json=body)
    assert missing.status_code == 404 and missing.json()['detail'] == 'Payroll QR label not found'
    blank = c.client.patch(f'/api/payroll/qr-labels/{lid}', headers=c.headers, json=body)
    assert blank.status_code == 400 and blank.json()['detail'] == 'Payroll QR operation name is required'
    negative = c.client.patch('/api/payroll/qr-labels/99999999', headers=c.headers, json={'operation_name': 'Valid', 'rate_per_piece': -1})
    assert negative.status_code == 422
    with c.sessions() as db:
        db.get(PayrollQrLabel, lid).status = 'closed'
        db.commit()
    closed_blank = c.client.patch(f'/api/payroll/qr-labels/{lid}', headers=c.headers, json=body)
    assert closed_blank.status_code == 409 and closed_blank.json()['detail'].startswith('Only never-scanned')
    with c.sessions() as db:
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='edit_unscanned_qr').count() == 0


@pytest.mark.parametrize('history', ['original_uid', 'return_count', 'last_scanned_at', 'linked_record'])
def test_edit_never_scanned_guards_preserve_values_and_audit(edit_case, history):
    c = edit_case
    label, lid = _issued(c)
    with c.sessions() as db:
        row = db.get(PayrollQrLabel, lid)
        if history == 'original_uid':
            db.get(PayrollRecord, c.record_id).original_scan_uid = label['label_uid']
        elif history == 'return_count':
            row.return_count = 1
        elif history == 'last_scanned_at':
            row.last_scanned_at = c.stamp
        else:
            row.payroll_record_id = c.record_id
        db.commit()
    result = c.client.patch(f'/api/payroll/qr-labels/{lid}', headers=c.headers, json={'operation_name': 'Forbidden edit', 'rate_per_piece': 2})
    assert result.status_code == 409, result.text
    with c.sessions() as db:
        row = db.get(PayrollQrLabel, lid)
        assert row.operation_name == 'Sew' and row.rate_per_piece == Decimal('1.2345')
        assert row.payload == 'original printed snapshot'
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='edit_unscanned_qr').count() == 0


def test_edit_precommit_failure_rolls_back_values_audit_then_retry(edit_case):
    c = edit_case
    _, lid = _issued(c)
    body = {'operation_name': 'Retry edit', 'rate_per_piece': '3.50'}
    def fail_commit(session):
        raise RuntimeError('characterized QR edit commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='characterized QR edit commit failure'):
            c.client.patch(f'/api/payroll/qr-labels/{lid}', headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        row = db.get(PayrollQrLabel, lid)
        assert row.operation_name == 'Sew' and row.rate_per_piece == Decimal('1.2345')
        assert row.payload == 'original printed snapshot'
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='edit_unscanned_qr').count() == 0
    retried = c.client.patch(f'/api/payroll/qr-labels/{lid}', headers=c.headers, json=body)
    assert retried.status_code == 200 and retried.json()['operation_name'] == 'Retry edit', retried.text
    with c.sessions() as db:
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='edit_unscanned_qr').count() == 1
