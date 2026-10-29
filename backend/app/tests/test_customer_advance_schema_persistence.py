"""Customer advances participate in the receipt's existing transaction."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.models import payments_service
from app.models.finance import customer_ledger_service
from app.models.idempotency_service import bind_idempotency_identity
from app.schemas import AuditLog, Customer, IdempotencyRecord, Payment, User
from app.tests.conftest import TestSessionLocal


def test_advance_uses_caller_transaction_and_rollback(monkeypatch):
    with TestSessionLocal() as db:
        customer = Customer(name="Synthetic advance transaction")
        db.add(customer)
        db.commit()
        customer_id = customer.id

        def no_commit():
            raise AssertionError("advance insertion must not commit")

        monkeypatch.setattr(db, "commit", no_commit)
        local_time = datetime(2025, 2, 3, 12, 30, tzinfo=timezone(timedelta(hours=5)))
        payment = payments_service.create_customer_advance_payment(
            db, customer_id=customer_id, amount=Decimal("0.29"),
            payment_method="legacy-custom-method", paid_at=local_time, notes="synthetic",
        )
        payment_id = payment.id
        assert payment.invoice_id is None and payment.customer_id == customer_id
        assert payment.amount == Decimal("0.29")
        assert payment.paid_at == datetime(2025, 2, 3, 7, 30, tzinfo=timezone.utc)
        assert payment.payment_method == "legacy-custom-method" and payment.notes == "synthetic"
        assert db.get(Payment, payment_id) is payment
        db.rollback()

    with TestSessionLocal() as db:
        assert db.get(Payment, payment_id) is None


def test_late_receipt_failure_rolls_back_advance_and_audit(monkeypatch):
    with TestSessionLocal() as db:
        customer = Customer(name="Synthetic advance rollback")
        db.add(customer)
        db.commit()
        cid = customer.id
        actor = db.query(User).first()
        bind_idempotency_identity(db, actor)
        before_audit = db.query(AuditLog).count()
        before_keys = db.query(IdempotencyRecord).count()

        def fail_after_audit(*args, **kwargs):
            raise RuntimeError("synthetic late failure")

        monkeypatch.setattr(customer_ledger_service, "store_idempotent_response", fail_after_audit)
        with pytest.raises(RuntimeError, match="synthetic late failure"):
            customer_ledger_service.record_customer_payment(
                db, cid, CustomerPaymentIn(amount=0.29, payment_method="cash"), actor, "advance-rollback",
            )
        assert db.query(Payment).filter_by(customer_id=cid).count() == 1
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Payment).filter_by(customer_id=cid).count() == 0
        assert db.query(AuditLog).count() == before_audit
        assert db.query(IdempotencyRecord).count() == before_keys
