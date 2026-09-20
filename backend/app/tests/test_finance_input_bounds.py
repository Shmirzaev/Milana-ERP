"""Reject values PostgreSQL cannot store before starting financial writes."""

import pytest
from pydantic import ValidationError

from app.db.session import SessionLocal
from app.models import Invoice, Payment
from app.schemas.sales import InvoiceIn, PaymentIn
from app.tests.test_payment_integrity import _create_invoice


@pytest.mark.parametrize("amount", [-1, 0, .001, float("nan"), float("inf"), float("-inf"), 1_000_000_000_000])
def test_payment_schema_rejects_nonpositive_subcent_nonfinite_and_overflow(amount):
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=1, amount=amount)


@pytest.mark.parametrize("amount", [-1, float("nan"), float("inf"), float("-inf"), 1_000_000_000_000])
def test_invoice_schema_rejects_negative_nonfinite_and_overflow(amount):
    with pytest.raises(ValidationError):
        InvoiceIn(sales_order_id=1, amount=amount)


@pytest.mark.parametrize("value", [0, -1, 2_147_483_648])
def test_finance_references_fit_positive_postgres_integer(value):
    with pytest.raises(ValidationError):
        InvoiceIn(sales_order_id=value)
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=value, amount=1)


def test_finance_schema_preserves_supported_coercion_zero_invoice_and_nullable_method():
    assert InvoiceIn(sales_order_id="1").amount is None
    assert InvoiceIn(sales_order_id=1, amount=0).amount == 0
    assert PaymentIn(invoice_id="1", amount="0.01").amount == .01
    assert PaymentIn(invoice_id=1, amount=999_999_999_999.99).amount == 999_999_999_999.99
    assert PaymentIn(invoice_id=1, amount=1, payment_method=None).payment_method is None
    assert PaymentIn(invoice_id=1, amount=1, payment_method="x" * 32).payment_method == "x" * 32
    with pytest.raises(ValidationError):
        PaymentIn(invoice_id=1, amount=1, payment_method="x" * 33)


@pytest.mark.parametrize("patch", [{"amount": 0}, {"amount": -.01}, {"amount": .001},
                                    {"amount": 1_000_000_000_000}, {"payment_method": "x" * 33}])
def test_payment_api_rejects_invalid_values_without_database_changes(client, auth_headers, patch):
    _, _, invoice_id = _create_invoice(SessionLocal)
    response = client.post("/api/finance/payments", json={"invoice_id": invoice_id, "amount": 1, **patch},
                           headers=auth_headers)
    assert response.status_code == 422, response.text
    with SessionLocal() as db:
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 0
        assert db.get(Invoice, invoice_id).status == "unpaid"
