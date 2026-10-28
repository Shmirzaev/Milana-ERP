"""Receipt auto-issuance and the split advance share one transaction."""
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder

from app.libs.dto.sales.customer_payment_input import CustomerPaymentIn
from app.libs.enums.finance import InvoiceStatus
from app.models.finance import customer_ledger_service as ledger
from app.models.idempotency_service import bind_idempotency_identity
from app.models.numbering_service import next_invoice_no
from app.schemas import AuditLog, Customer, IdempotencyRecord, Invoice, Payment, SalesOrder, User
from app.tests.conftest import TestSessionLocal


def _order(db):
    customer = Customer(name="Synthetic receipt invoice")
    db.add(customer)
    db.flush()
    order = SalesOrder(order_no=f"RECEIPT-{uuid4().hex}", customer_id=customer.id, total_amount=Decimal("1.00"))
    db.add(order)
    db.commit()
    return customer.id, order.id


def test_auto_invoice_split_advance_and_idempotent_replay(monkeypatch):
    with TestSessionLocal() as db:
        cid, oid = _order(db)
        actor = db.query(User).first()
        bind_idempotency_identity(db, actor)
        expected_no = next_invoice_no(db)
        real_insert = ledger.insert_order_invoice
        observed = []

        def observe(session, **kwargs):
            observed.append((session, kwargs["status"]))
            return real_insert(session, **kwargs)

        monkeypatch.setattr(ledger, "insert_order_invoice", observe)
        payload = CustomerPaymentIn(sales_order_id=oid, amount=1.29, payment_method="cash")
        response = ledger.record_customer_payment(db, cid, payload, actor, "split-replay")
        assert observed == [(db, InvoiceStatus.UNPAID)]
        invoice = db.query(Invoice).filter_by(sales_order_id=oid).one()
        payments = db.query(Payment).filter_by(customer_id=cid).order_by(Payment.id).all()
        assert invoice.invoice_no == expected_no and invoice.amount == Decimal("1.00")
        assert invoice.status is InvoiceStatus.PAID
        assert [(p.invoice_id, p.amount) for p in payments] == [(invoice.id, Decimal("1.00")), (None, Decimal("0.29"))]
        assert response["id"] == payments[-1].id and response["is_advance"] is True
        assert response["order_id"] is None and response["invoice_id"] is None
        before = (db.query(AuditLog).count(), db.query(IdempotencyRecord).count())
        replay = ledger.record_customer_payment(db, cid, payload, actor, "split-replay")
        assert replay == jsonable_encoder(response)
        assert len(observed) == 1 and db.query(Invoice).filter_by(sales_order_id=oid).count() == 1
        assert db.query(Payment).filter_by(customer_id=cid).count() == 2
        assert (db.query(AuditLog).count(), db.query(IdempotencyRecord).count()) == before


def test_late_failure_rolls_back_invoice_number_payments_audit_and_retry(monkeypatch):
    with TestSessionLocal() as db:
        cid, oid = _order(db)
        actor = db.query(User).first()
        bind_idempotency_identity(db, actor)
        expected_no = next_invoice_no(db)
        before = (db.query(AuditLog).count(), db.query(IdempotencyRecord).count())
        store = ledger.store_idempotent_response

        def store_then_fail(*args, **kwargs):
            store(*args, **kwargs)
            db.flush()
            raise RuntimeError("synthetic late receipt failure")

        monkeypatch.setattr(ledger, "store_idempotent_response", store_then_fail)
        with pytest.raises(RuntimeError, match="synthetic late receipt failure"):
            ledger.record_customer_payment(
                db, cid, CustomerPaymentIn(sales_order_id=oid, amount=1.29), actor, "split-rollback",
            )
        assert db.query(Invoice).filter_by(sales_order_id=oid).count() == 1
        assert db.query(Payment).filter_by(customer_id=cid).count() == 2
        db.rollback()

    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=oid).count() == 0
        assert db.query(Payment).filter_by(customer_id=cid).count() == 0
        assert (db.query(AuditLog).count(), db.query(IdempotencyRecord).count()) == before
        assert next_invoice_no(db) == expected_no
