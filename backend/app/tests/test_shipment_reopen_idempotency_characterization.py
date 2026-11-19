"""Preserve shipment receipt invalidation policy and the caller's transaction."""
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import object_session

from app.libs.enums.finance import InvoiceStatus
from app.models import shipment_reopen_service
from app.models.idempotency_service import (
    bind_idempotency_identity, replay_idempotent_response, request_fingerprint,
    store_idempotent_response,
)
from app.schemas import AuditLog, FinishedGoodsStock, IdempotencyRecord, Invoice, Shipment, User
from app.tests.conftest import TestSessionLocal
from app.tests.test_shipment_reopen_invoice_postgres import (
    _payload, _shipment_case, customer_pg_sessions,  # noqa: F401
)


@pytest.fixture(params=['sqlite', 'postgres'])
def receipt_case(request):
    sessions = TestSessionLocal if request.param == 'sqlite' else request.getfixturevalue('customer_pg_sessions')
    with sessions.begin() as db:
        actor = User(name='Retry invalidation actor', email=f'reopen-hash-{uuid4().hex}@example.invalid',
                     password_hash='unused', factory_code='MIL')
        db.add(actor)
        db.flush()
        actor_id = actor.id
    case = _shipment_case(sessions, actor_id)
    expected = {record_id: True for record_id in case['idempotency_ids']}
    with sessions() as db:
        actor = db.get(User, actor_id)
        bind_idempotency_identity(db, actor)
        replay_key = 'reopen-v2-' + uuid4().hex
        store_idempotent_response(db, scope='shipments.scan-package', key=replay_key, payload={},
                                  response={'package_id': case['package_id'], 'factory_code': 'MIL'}, user=actor)
        saved = db.query(IdempotencyRecord).filter_by(key=replay_key).one()
        expected[saved.id] = True
        matrix = [
            ('shipments.update', {'shipment_id': case['shipment_id']}, True),
            ('shipments.deliver:v2:' + 'e' * 64, {'id': case['shipment_id']}, True),
            ('shipments.scan-package', {'package_id': case['package_id']}, True),
            ('shipments.ship', {'shipment_id': case['shipment_id'], 'factory_code': 'ECO'}, True),
            ('shipments.ship', {'id': case['shipment_id'] + 1000000}, False),
            ('shipments.scan-package', {'package_id': case['package_id'] + 1000000}, False),
            ('shipments.scan-package-extra', {'package_id': case['package_id']}, False),
            ('finance.payments', {'shipment_id': case['shipment_id']}, False),
        ]
        for scope, response, changes in matrix:
            row = IdempotencyRecord(scope=scope, key=uuid4().hex, request_hash=request_fingerprint({}),
                                    response_json=response, user_id=actor_id, status_code=200)
            db.add(row)
            db.flush()
            expected[row.id] = changes
        db.commit()
    return sessions, case, expected, replay_key


def _receipts(sessions, expected):
    with sessions() as db:
        return {row.id: (row.request_hash, row.scope, row.key, row.response_json, row.status_code, row.user_id)
                for row in db.query(IdempotencyRecord).filter(IdempotencyRecord.id.in_(expected))}


def _assert_hashes(before, after, expected):
    assert before.keys() == after.keys()
    for record_id, changes in expected.items():
        expected_hash = sha256(('shipment-reopened:' + before[record_id][0]).encode()).hexdigest() if changes else before[record_id][0]
        assert after[record_id][0] == expected_hash
        assert after[record_id][1:] == before[record_id][1:]


def test_reopen_invalidates_exact_legacy_v2_and_package_receipts_without_early_commit(receipt_case, monkeypatch):
    sessions, case, expected, replay_key = receipt_case
    before = _receipts(sessions, expected)
    calls, commits = [], []
    helper = getattr(shipment_reopen_service, 'set_idempotency_request_hash', None)
    with sessions() as db:
        if helper is not None:
            def record_write(record, request_hash):
                assert object_session(record) is db
                calls.append((record.id, request_hash))
                return helper(record, request_hash)
            monkeypatch.setattr(shipment_reopen_service, 'set_idempotency_request_hash', record_write)
        event.listen(db, 'after_commit', lambda session: commits.append(session))
        result = shipment_reopen_service.reopen_shipment(db, case['shipment_id'], _payload(case), db.get(User, case['actor_id']))
        assert result.status == 'created' and db.in_transaction() and commits == []
        if helper is not None:
            assert {record_id for record_id, _ in calls} == {record_id for record_id, changed in expected.items() if changed}
        db.rollback()
    assert _receipts(sessions, expected) == before
    # Use the original helper on the second independent operation Session.
    if helper is not None:
        monkeypatch.setattr(shipment_reopen_service, 'set_idempotency_request_hash', helper)
    with sessions() as db:
        assert db.get(Shipment, case['shipment_id']).status == 'shipped'
        shipment_reopen_service.reopen_shipment(db, case['shipment_id'], _payload(case), db.get(User, case['actor_id']))
        db.commit()
    _assert_hashes(before, _receipts(sessions, expected), expected)
    with sessions() as db:
        actor = db.get(User, case['actor_id'])
        bind_idempotency_identity(db, actor)
        with pytest.raises(HTTPException) as conflict:
            replay_idempotent_response(db, scope='shipments.scan-package', key=replay_key, payload={})
        assert conflict.value.status_code == 409
        assert db.query(AuditLog).filter_by(action='reopen_shipment', entity_id=case['shipment_id']).count() == 1


def test_reopen_audit_failure_rolls_back_every_receipt_hash_then_retry(receipt_case, monkeypatch):
    sessions, case, expected, _ = receipt_case
    before = _receipts(sessions, expected)
    def fail_after_hashes(*args, **kwargs):
        raise RuntimeError('characterized receipt invalidation audit failure')
    with monkeypatch.context() as patch:
        patch.setattr(shipment_reopen_service, 'log_action', fail_after_hashes)
        with sessions() as db:
            with pytest.raises(RuntimeError, match='characterized receipt invalidation audit failure'):
                shipment_reopen_service.reopen_shipment(db, case['shipment_id'], _payload(case), db.get(User, case['actor_id']))
            db.rollback()
    assert _receipts(sessions, expected) == before
    with sessions() as db:
        assert db.get(Shipment, case['shipment_id']).status == 'shipped'
        assert db.get(Invoice, case['invoice_id']).status is InvoiceStatus.UNPAID
        assert db.get(FinishedGoodsStock, case['stock_id']).sold_qty == 2
        assert db.query(AuditLog).filter_by(action='reopen_shipment', entity_id=case['shipment_id']).count() == 0
        shipment_reopen_service.reopen_shipment(db, case['shipment_id'], _payload(case), db.get(User, case['actor_id']))
        db.commit()
    _assert_hashes(before, _receipts(sessions, expected), expected)
