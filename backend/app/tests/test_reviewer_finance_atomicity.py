"""Independent API/DB challenges for the forthcoming schema writer extraction."""
from decimal import Decimal
from uuid import uuid4
import pytest

from app.db.session import SessionLocal
from app.schemas import AuditLog, IdempotencyRecord, Invoice, Payment
from app.models.finance import payments_service
from app.tests.test_finance_payment_operation_contract import payable_invoice


def counts(invoice_id):
    with SessionLocal() as db:
        return (db.get(Invoice, invoice_id).status,
                db.query(Payment).filter_by(invoice_id=invoice_id).count(),
                db.query(AuditLog).filter_by(entity_type='Payment').count(),
                db.query(IdempotencyRecord).count())


def test_keyed_replay_and_conflicting_retry_preserve_one_atomic_payment(client, auth_headers, payable_invoice):
    _, invoice_id = payable_invoice
    headers = {**auth_headers, 'Idempotency-Key': 'review-' + uuid4().hex}
    body = {'invoice_id': invoice_id, 'amount': 40}
    before = counts(invoice_id)
    first = client.post('/api/finance/payments', headers=headers, json=body)
    assert first.status_code == 201, first.text
    after = counts(invoice_id)
    assert after == ('partially_paid', before[1] + 1, before[2] + 1, before[3] + 1)
    replay = client.post('/api/finance/payments', headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == first.json()
    conflict = client.post('/api/finance/payments', headers=headers, json={**body, 'amount': 41})
    assert conflict.status_code == 409, conflict.text
    assert counts(invoice_id) == after
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).one().amount == Decimal('40')


@pytest.mark.parametrize('failure_hook', ['log_action', 'store_idempotent_response'])
def test_late_failure_rolls_back_payment_status_audit_and_retry_record(client, auth_headers, payable_invoice, monkeypatch, failure_hook):
    _, invoice_id = payable_invoice
    before = counts(invoice_id)
    original = getattr(payments_service, failure_hook)

    def fail_after_participant_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('reviewer simulated participant failure')

    monkeypatch.setattr(payments_service, failure_hook, fail_after_participant_write)
    headers = {**auth_headers, 'Idempotency-Key': 'review-failure-' + uuid4().hex}
    body = {'invoice_id': invoice_id, 'amount': 100}
    with pytest.raises(RuntimeError, match='reviewer simulated participant failure'):
        client.post('/api/finance/payments', headers=headers, json=body)
    assert counts(invoice_id) == before
    monkeypatch.setattr(payments_service, failure_hook, original)
    retry = client.post('/api/finance/payments', headers=headers, json=body)
    assert retry.status_code == 201, retry.text
    assert counts(invoice_id) == ('paid', before[1] + 1, before[2] + 1, before[3] + 1)
