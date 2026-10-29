"""Schema-owned write coverage for the finance invoice payment operation.

These tests assert that the mapped writes of "record an invoice payment"
actually happen in the schema layer, that the schema helper keeps an explicit
field contract, and that the outer service still owns the transaction.

They deliberately do not restate the invoice status vocabulary: the allowed
and forbidden states are already covered with independent expected values in
`test_finance_payment_operation_contract.py`, and the atomicity of Payment +
Invoice.status + AuditLog + IdempotencyRecord is covered by the reviewer's
`test_reviewer_finance_atomicity.py`.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.libs.enums.finance import InvoiceStatus
from app.models import idempotency_service, payments_service
from app.schemas import AuditLog, IdempotencyRecord, Invoice, Payment
from app.schemas.finance.invoice_payment_persistence import insert_invoice_payment
from app.tests.conftest import TestSessionLocal
from app.tests.test_finance_payment_operation_contract import payable_invoice  # noqa: F401


def _pay(client, auth_headers, invoice_id, amount, *, headers=None, **extra):
    body = {"invoice_id": invoice_id, "amount": float(amount)}
    body.update(extra)
    return client.post("/api/finance/payments", headers=headers or auth_headers, json=body)


def test_payment_row_is_written_through_the_schema_helper(client, auth_headers, payable_invoice, monkeypatch):
    """The service delegates the `payments` insert to the schema layer."""
    _customer_id, invoice_id = payable_invoice
    calls = []
    original = payments_service.insert_invoice_payment

    def recording(db, **kwargs):
        calls.append(kwargs)
        return original(db, **kwargs)

    monkeypatch.setattr(payments_service, "insert_invoice_payment", recording)
    response = _pay(client, auth_headers, invoice_id, Decimal("40"))
    assert response.status_code == 201, response.text

    assert len(calls) == 1, calls
    call = calls[0]
    assert call["invoice_id"] == invoice_id
    assert call["customer_id"] is not None
    assert call["amount"] == Decimal("40")
    assert call["payment_method"] is None
    assert call["notes"] is None
    assert call["paid_at"] is not None

    with TestSessionLocal() as db:
        stored = db.query(Payment).filter_by(invoice_id=invoice_id).one()
    assert stored.amount == Decimal("40")


def test_invoice_status_is_written_through_the_schema_helper(client, auth_headers, payable_invoice, monkeypatch):
    """The mapped `invoices.status` update is a schema-owned operation."""
    _customer_id, invoice_id = payable_invoice
    calls = []
    original = payments_service.set_invoice_status

    def recording(invoice, status):
        calls.append((invoice.id, status))
        return original(invoice, status)

    monkeypatch.setattr(payments_service, "set_invoice_status", recording)
    response = _pay(client, auth_headers, invoice_id, Decimal("40"))
    assert response.status_code == 201, response.text

    assert calls == [(invoice_id, InvoiceStatus.PARTIALLY_PAID)]
    assert calls[0][1] is InvoiceStatus.PARTIALLY_PAID
    with TestSessionLocal() as db:
        assert db.get(Invoice, invoice_id).status == "partially_paid"


def test_schema_helper_leaves_the_columns_this_operation_does_not_own_unset(
    client, auth_headers, payable_invoice
):
    """`external_source` and `external_id` keep their column defaults."""
    _customer_id, invoice_id = payable_invoice
    response = _pay(client, auth_headers, invoice_id, Decimal("10"))
    assert response.status_code == 201, response.text

    with TestSessionLocal() as db:
        stored = db.query(Payment).filter_by(invoice_id=invoice_id).one()
    assert stored.external_source is None
    assert stored.external_id is None


def test_schema_helper_keeps_the_money_exact(client, auth_headers, payable_invoice):
    """The schema write does not round the amount through a binary float."""
    _customer_id, invoice_id = payable_invoice
    response = _pay(client, auth_headers, invoice_id, Decimal("99.99"))
    assert response.status_code == 201, response.text

    with TestSessionLocal() as db:
        stored = db.query(Payment).filter_by(invoice_id=invoice_id).one()
    assert stored.amount == Decimal("99.99")
    assert isinstance(stored.amount, Decimal)


def test_schema_helper_does_not_commit_or_open_its_own_transaction(payable_invoice):
    """Only the outer operation commits; the helper stages and flushes."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        payment = insert_invoice_payment(
            db,
            invoice_id=invoice_id,
            customer_id=None,
            amount=Decimal("5"),
            payment_method=None,
            paid_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            notes=None,
        )
        assert payment.id is not None, "the helper flushes its own insert"
        # Another session cannot see the row: the helper never committed.
        with TestSessionLocal() as other:
            assert other.query(Payment).filter_by(id=payment.id).first() is None
        db.rollback()
    with TestSessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 0


def test_schema_helper_has_no_mass_assignment_hole(payable_invoice):
    """The helper only accepts the fields it declares."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        with pytest.raises(TypeError):
            insert_invoice_payment(
                db,
                invoice_id=invoice_id,
                customer_id=None,
                amount=Decimal("5"),
                payment_method=None,
                paid_at=None,
                notes=None,
                external_source="not-allowed",
            )


def test_idempotency_row_is_written_through_the_schema_helper(
    client, auth_headers, payable_invoice, monkeypatch
):
    """The `idempotency_records` insert is a schema-owned operation."""
    _customer_id, invoice_id = payable_invoice
    calls = []
    original = idempotency_service.insert_idempotency_record

    def recording(db, **kwargs):
        calls.append(kwargs)
        return original(db, **kwargs)

    monkeypatch.setattr(idempotency_service, "insert_idempotency_record", recording)
    key = f"schema-write-{uuid4().hex}"
    headers = {**auth_headers, "Idempotency-Key": key}
    response = _pay(client, auth_headers, invoice_id, Decimal("10"), headers=headers)
    assert response.status_code == 201, response.text

    assert len(calls) == 1, calls
    call = calls[0]
    assert call["key"] == key
    assert call["status_code"] == 201
    assert call["user_id"] is not None
    assert call["request_hash"] and isinstance(call["request_hash"], str)
    assert call["scope"].startswith("finance.payments:v2:")

    with TestSessionLocal() as db:
        row = db.query(IdempotencyRecord).filter_by(key=key).one()
    assert row.status_code == 201
    assert row.user_id == call["user_id"]
    assert row.request_hash == call["request_hash"]


def test_the_service_still_owns_the_audit_row_and_the_single_commit(
    client, auth_headers, payable_invoice
):
    """Audit stays a service participant and one request writes one payment."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        audit_before = db.query(AuditLog).filter_by(entity_type="Payment").count()
    response = _pay(client, auth_headers, invoice_id, Decimal("10"))
    assert response.status_code == 201, response.text

    with TestSessionLocal() as db:
        audit_after = db.query(AuditLog).filter_by(entity_type="Payment").count()
        payments = db.query(Payment).filter_by(invoice_id=invoice_id).all()
        entry = db.query(AuditLog).filter_by(entity_type="Payment").order_by(AuditLog.id.desc()).first()
    assert audit_after == audit_before + 1
    assert len(payments) == 1, "one request must not write a second payment row"
    assert entry.action == "create"
    assert entry.entity_id == payments[0].id
