import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.routes.payroll import router
from app.core.deps import DbSession, require_permissions
from app.libs.dto.people.payroll import PayrollQrLabelBatchDeleteIn, PayrollQrLabelBatchDeleteOut
from app.models.people import payroll_qr_service
from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord, User
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue

@pytest.fixture
def delete_case(payroll_case):
    c = payroll_case
    if not hasattr(payroll_qr_service, 'delete_qr_label_batch'):
        yield c
        return
    app, calls = FastAPI(), []

    @app.post('/api/payroll/qr-labels/delete-batch', response_model=PayrollQrLabelBatchDeleteOut)
    def candidate_delete(payload: PayrollQrLabelBatchDeleteIn, db: DbSession,
                         current: User = Depends(require_permissions('payroll.manage', '*'))):
        calls.append(tuple(payload.label_ids))
        return payroll_qr_service.delete_qr_label_batch(payload, db, current)

    app.include_router(router, prefix='/api')
    app.dependency_overrides.update(c.client.app.dependency_overrides)
    with TestClient(app) as client:
        c.client = client
        yield c
    assert calls, 'Candidate delete service was never invoked'


def test_delete_unscanned_batch_preserves_size_guard_and_audit(delete_case):
    c = delete_case
    label = issue(c.client, c.headers)
    with c.sessions() as db:
        lid = db.query(PayrollQrLabel.id).filter_by(label_uid=label['label_uid']).scalar()
    body = {'label_ids': [lid, lid], 'size': 'L'}
    url = '/api/payroll/qr-labels/delete-batch'
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    assert c.client.post(url, headers=c.headers, json={**body, 'size': 'M'}).status_code == 409
    r = c.client.post(url, headers=c.headers, json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {'deleted_count': 1, 'size': 'L'}
    assert c.client.post(url, headers=c.headers, json=body).status_code == 404
    with c.sessions() as db:
        assert db.get(PayrollQrLabel, lid) is None
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='delete_unscanned_batch').one()
        assert audit.old_value_json['label_ids'] == [lid] and audit.entry_hash


@pytest.mark.parametrize('guard', ['size', 'order', 'history', 'linked', 'return_count', 'factory'])
def test_batch_delete_refuses_any_used_mixed_or_foreign_row_atomically(delete_case, guard):
    c = delete_case
    issued = [issue(c.client, c.headers), issue(c.client, c.headers)]
    with c.sessions() as db:
        rows = [db.query(PayrollQrLabel).filter_by(label_uid=item['label_uid']).one() for item in issued]
        ids = [row.id for row in rows]
        second = rows[1]
        if guard == 'size':
            second.size = 'M'
        elif guard == 'order':
            second.production_no = 'OTHER-ORDER'
        elif guard == 'history':
            db.get(PayrollRecord, c.record_id).original_scan_uid = second.label_uid
        elif guard == 'linked':
            second.payroll_record_id = c.record_id
        elif guard == 'return_count':
            second.return_count = 1
        else:
            second.factory_code = 'ECO'
        db.commit()
    result = c.client.post('/api/payroll/qr-labels/delete-batch', headers=c.headers, json={'label_ids': ids, 'size': 'L'})
    assert result.status_code == (404 if guard == 'factory' else 409), result.text
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.id.in_(ids)).count() == 2
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, action='delete_unscanned_batch').count() == 0


def test_batch_delete_precommit_failure_rolls_back_rows_and_audit_then_retries(delete_case):
    c = delete_case
    issued = [issue(c.client, c.headers), issue(c.client, c.headers)]
    with c.sessions() as db:
        ids = [db.query(PayrollQrLabel.id).filter_by(label_uid=item['label_uid']).scalar() for item in issued]
    body = {'label_ids': ids, 'size': 'L'}
    def fail_commit(session):
        raise RuntimeError('characterized QR delete commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='characterized QR delete commit failure'):
            c.client.post('/api/payroll/qr-labels/delete-batch', headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.id.in_(ids)).count() == 2
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, action='delete_unscanned_batch').count() == 0
    retried = c.client.post('/api/payroll/qr-labels/delete-batch', headers=c.headers, json=body)
    assert retried.status_code == 200 and retried.json()['deleted_count'] == 2, retried.text
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter(PayrollQrLabel.id.in_(ids)).count() == 0
        assert db.query(AuditLog).filter_by(user_id=c.actor_id, action='delete_unscanned_batch').count() == 1
