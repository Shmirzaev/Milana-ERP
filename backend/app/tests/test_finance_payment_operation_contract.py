"""RF-011 operation 01 - record an invoice payment (POST /api/finance/payments).

Operation under study
---------------------
route              POST /api/finance/payments -> app/api/routes/finance.py:create_payment
service            app/models/finance/payments_service.py:record_invoice_payment
low-level writer   app/models/payments_service.py:create_invoice_payment
settlement rule    app/models/payments_service.py:invoice_payment_status
ORM fields         invoices.status  VARCHAR(32) NOT NULL DEFAULT 'unpaid'
                                       CHECK ck_invoices_status
                   payments         one row per accepted payment, no status column
transaction owner  record_invoice_payment (the only commit in the operation)
external effects   one payments row, one Payment audit row, one idempotency row,
                   and the refreshed invoices.status

Vocabulary of this operation
----------------------------
`invoices.status` is the only vocabulary the operation writes, and it is the
persisted `InvoiceStatus` vocabulary. This operation may only leave an invoice
in its ACTIVE subset. VOID and CANCELLED are refused before any write, so
membership in the enum never authorises a transition.

`payment_method` is user-entered free-form data (`VARCHAR(32)`, nullable) and
`PaymentIn.payment_method` stays `Optional[str]`: this operation centralises
the persisted vocabulary, it does not narrow the accepted request values.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.libs.enums.finance import InvoiceStatus
from app.models.payments_service import (
    REVERSED_INVOICE_STATUSES,
    invoice_payment_status,
)
from app.schemas import AuditLog, Customer, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal

# Expected values are written here as independent literals taken from the
# business contract, NOT derived from `InvoiceStatus`. Deriving an expected
# value from the enum under test would hide a missing or misspelled member.
# `test_the_persisted_enum_matches_the_business_contract` is the separate
# check that holds the enum and these literals together.
EXPECTED_ACTIVE_STATUSES = ("unpaid", "partially_paid", "paid")
EXPECTED_REFUSED_STATUSES = ("void", "cancelled")
EXPECTED_PERSISTED_STATUSES = EXPECTED_ACTIVE_STATUSES + EXPECTED_REFUSED_STATUSES


@pytest.fixture
def payable_invoice():
    """A committed unpaid invoice of 100 with its owning customer."""
    with TestSessionLocal() as db:
        customer = Customer(name="Synthetic finance payment operation")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"OP01-{uuid4().hex}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(
            invoice_no=f"OP01-INV-{uuid4().hex}",
            sales_order_id=order.id,
            amount=Decimal("100"),
            status="unpaid",
        )
        db.add(invoice)
        db.commit()
        return customer.id, invoice.id


def _pay(client, auth_headers, invoice_id, amount, **extra):
    body = {"invoice_id": invoice_id, "amount": float(amount)}
    body.update(extra)
    return client.post("/api/finance/payments", headers=auth_headers, json=body)


def test_the_persisted_enum_matches_the_business_contract():
    """The enum defines exactly the five persisted states and nothing else."""
    assert [status.value for status in InvoiceStatus] == list(EXPECTED_PERSISTED_STATUSES)
    assert set(REVERSED_INVOICE_STATUSES) == set(EXPECTED_REFUSED_STATUSES)
    assert not set(EXPECTED_ACTIVE_STATUSES) & set(REVERSED_INVOICE_STATUSES)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0.01"), "partially_paid"),
        (Decimal("40"), "partially_paid"),
        (Decimal("99.00"), "paid"),
        (Decimal("100"), "paid"),
    ],
)
def test_operation_01_writes_only_an_active_status_of_the_persisted_enum(
    client, auth_headers, payable_invoice, amount, expected
):
    """Every status this operation writes is an active persisted state."""
    _customer_id, invoice_id = payable_invoice
    response = _pay(client, auth_headers, invoice_id, amount)
    assert response.status_code == 201, response.text

    with TestSessionLocal() as db:
        stored = db.get(Invoice, invoice_id).status
    assert stored == expected
    assert stored in EXPECTED_ACTIVE_STATUSES
    assert stored not in EXPECTED_REFUSED_STATUSES


def test_operation_01_settlement_derivation_stays_inside_the_active_subset():
    """The shared settlement rule cannot leave an invoice outside the subset."""
    active = set(EXPECTED_ACTIVE_STATUSES)
    for amount, paid in [
        (Decimal("100"), Decimal("0")),
        (Decimal("100"), Decimal("0.01")),
        (Decimal("100"), Decimal("40")),
        (Decimal("100"), Decimal("99")),
        (Decimal("100"), Decimal("100")),
        (Decimal("1"), Decimal("0")),
    ]:
        assert invoice_payment_status(amount, paid) in active


@pytest.mark.parametrize("status", EXPECTED_REFUSED_STATUSES)
def test_operation_01_refuses_a_reversed_invoice_and_writes_nothing(
    client, auth_headers, payable_invoice, status
):
    """A reversed invoice is refused before any row is written."""
    _customer_id, invoice_id = payable_invoice
    with TestSessionLocal() as db:
        db.get(Invoice, invoice_id).status = status
        db.commit()
        payments_before = db.query(Payment).filter_by(invoice_id=invoice_id).count()
        audit_before = db.query(AuditLog).filter(AuditLog.entity_type == "Payment").count()

    response = _pay(client, auth_headers, invoice_id, Decimal("10"))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Cannot pay a reversed or cancelled invoice"

    with TestSessionLocal() as db:
        assert db.get(Invoice, invoice_id).status == status
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == payments_before
        assert db.query(AuditLog).filter(AuditLog.entity_type == "Payment").count() == audit_before


@pytest.mark.parametrize("method", ["cash", "bank_transfer", "uzcard-tolgay", "anything at all"])
def test_operation_01_payment_method_stays_free_form(client, auth_headers, payable_invoice, method):
    """`payment_method` is user-entered data, not a closed vocabulary."""
    _customer_id, invoice_id = payable_invoice
    response = _pay(client, auth_headers, invoice_id, Decimal("10"), payment_method=method)
    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] == method

    with TestSessionLocal() as db:
        stored = db.query(Payment).filter_by(invoice_id=invoice_id).one()
    assert stored.payment_method == method


def test_operation_01_omitted_payment_method_stays_null(client, auth_headers, payable_invoice):
    """An omitted `payment_method` is still stored as null."""
    _customer_id, invoice_id = payable_invoice
    response = _pay(client, auth_headers, invoice_id, Decimal("10"))
    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] is None

    with TestSessionLocal() as db:
        stored = db.query(Payment).filter_by(invoice_id=invoice_id).one()
    assert stored.payment_method is None
