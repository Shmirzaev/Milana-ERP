from decimal import Decimal

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.api.routes.payroll import router
from app.core.deps import DbSession, require_permissions
from app.libs.dto.people.payroll import PayrollQrLabelSplitIn, PayrollQrLabelSplitOut
from app.models.people import payroll_qr_service
from app.schemas import AuditLog, PayrollQrLabel, PayrollRecord, User
from app.tests.payroll_operation_fixture import payroll_case, payroll_postgres_sessions  # noqa: F401
from app.tests.test_payroll_scan_allocations import issue

@pytest.fixture
def split_case(payroll_case):
    c = payroll_case
    if not hasattr(payroll_qr_service, 'split_qr_label'):
        yield c
        return
    app, calls = FastAPI(), []

    @app.post('/api/payroll/qr-labels/{label_id}/split', response_model=PayrollQrLabelSplitOut)
    def candidate_split(label_id: int, payload: PayrollQrLabelSplitIn, db: DbSession,
                        current: User = Depends(require_permissions('payroll.manage', '*'))):
        calls.append(label_id)
        return payroll_qr_service.split_qr_label(label_id, payload, db, current)

    app.include_router(router, prefix='/api')
    app.dependency_overrides.update(c.client.app.dependency_overrides)
    with TestClient(app) as client:
        c.client = client
        yield c
    assert calls, 'Candidate split service was never invoked'


def test_split_unscanned_label_preserves_quantity_and_supersedes_original(split_case):
    c = split_case
    label = issue(c.client, c.headers, quantity=20)
    with c.sessions() as db:
        lid = db.query(PayrollQrLabel.id).filter_by(label_uid=label['label_uid']).scalar()
    url = f'/api/payroll/qr-labels/{lid}/split'
    body = {'operation_name': 'Split sewing', 'rate_per_piece': '1.2345', 'quantities': [7, 13]}
    assert c.client.post(url, headers=c.denied, json=body).status_code == 403
    assert c.client.post(url, headers=c.headers, json={**body, 'quantities': [7, 12]}).status_code == 409
    r = c.client.post(url, headers=c.headers, json=body)
    assert r.status_code == 200, r.text
    assert r.json()['superseded_label_id'] == lid
    assert [Decimal(row['quantity']) for row in r.json()['labels']] == [7, 13]
    assert all(row['label_uid'] != label['label_uid'] and row['status'] == 'available' for row in r.json()['labels'])
    assert c.client.post(url, headers=c.headers, json=body).status_code == 409
    with c.sessions() as db:
        assert db.get(PayrollQrLabel, lid).status == 'superseded'
        assert db.query(PayrollQrLabel).filter_by(split_from_label_id=lid).count() == 2
        audit = db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='split_unscanned_qr').one()
        assert audit.new_value_json['quantities'] == [7, 13] and audit.entry_hash


@pytest.mark.parametrize('guard', ['sum', 'nonpositive', 'history', 'linked', 'superseded'])
def test_split_refusal_is_atomic_and_preserves_parent(split_case, guard):
    c = split_case
    issued = issue(c.client, c.headers, quantity=20)
    with c.sessions() as db:
        label = db.query(PayrollQrLabel).filter_by(label_uid=issued['label_uid']).one()
        lid = label.id
        if guard == 'history':
            db.get(PayrollRecord, c.record_id).original_scan_uid = label.label_uid
        elif guard == 'linked':
            label.payroll_record_id = c.record_id
        elif guard == 'superseded':
            label.status = 'superseded'
        db.commit()
    quantities = [7, 12] if guard == 'sum' else [7, 0, 13] if guard == 'nonpositive' else [7, 13]
    result = c.client.post(f'/api/payroll/qr-labels/{lid}/split', headers=c.headers,
                          json={'operation_name': 'Split sewing', 'rate_per_piece': '1.2345', 'quantities': quantities})
    assert result.status_code == (400 if guard == 'nonpositive' else 409), result.text
    with c.sessions() as db:
        label = db.get(PayrollQrLabel, lid)
        assert label.quantity == 20 and label.operation_name == 'Sew'
        assert db.query(PayrollQrLabel).filter_by(split_from_label_id=lid).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='split_unscanned_qr').count() == 0


def test_split_precommit_failure_rolls_back_children_parent_audit_then_retries(split_case):
    c = split_case
    issued = issue(c.client, c.headers, quantity=20)
    with c.sessions() as db:
        lid = db.query(PayrollQrLabel.id).filter_by(label_uid=issued['label_uid']).scalar()
    body = {'operation_name': 'Retry split', 'rate_per_piece': '1.2345', 'quantities': [7, 13]}
    def fail_commit(session):
        raise RuntimeError('characterized QR split commit failure')
    event.listen(c.sessions.class_, 'before_commit', fail_commit)
    try:
        with pytest.raises(RuntimeError, match='characterized QR split commit failure'):
            c.client.post(f'/api/payroll/qr-labels/{lid}/split', headers=c.headers, json=body)
    finally:
        event.remove(c.sessions.class_, 'before_commit', fail_commit)
    with c.sessions() as db:
        assert db.get(PayrollQrLabel, lid).status == 'available'
        assert db.query(PayrollQrLabel).filter_by(split_from_label_id=lid).count() == 0
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='split_unscanned_qr').count() == 0
    retried = c.client.post(f'/api/payroll/qr-labels/{lid}/split', headers=c.headers, json=body)
    assert retried.status_code == 200 and len(retried.json()['labels']) == 2, retried.text
    with c.sessions() as db:
        assert db.query(PayrollQrLabel).filter_by(split_from_label_id=lid).count() == 2
        assert db.query(AuditLog).filter_by(entity_type='PayrollQrLabel', entity_id=lid, action='split_unscanned_qr').count() == 1
