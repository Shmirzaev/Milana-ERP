from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.routes.partners import CustomerPaymentIn
from app.models import AuditLog, Customer, Invoice, Payment
from app.tests.conftest import TestSessionLocal


MAX_PAYMENT = Decimal("999999999999.99")


def _customer_id() -> int:
    with TestSessionLocal() as db:
        customer = Customer(name="Customer payment amount boundary")
        db.add(customer)
        db.commit()
        return int(customer.id)


def _write_counts() -> tuple[int, int, int]:
    with TestSessionLocal() as db:
        return (
            db.query(Payment).count(),
            db.query(Invoice).count(),
            db.query(AuditLog).count(),
        )


def test_customer_payment_schema_preserves_maximum_representable_amount():
    parsed = CustomerPaymentIn(amount=str(MAX_PAYMENT))

    assert parsed.amount == MAX_PAYMENT


@pytest.mark.parametrize("amount", [
    "1000000000000.00",
    "9999999999999.99",
    "1.00000000000000001",
    "1.001",
])
def test_customer_payment_schema_rejects_unrepresentable_amount(amount):
    with pytest.raises(ValidationError):
        CustomerPaymentIn(amount=amount)


@pytest.mark.parametrize("sales_order_id", [0, -1, 2_147_483_648])
def test_customer_payment_schema_rejects_invalid_sales_order_reference(sales_order_id):
    with pytest.raises(ValidationError):
        CustomerPaymentIn(sales_order_id=sales_order_id, amount="1.00")


def test_customer_payment_schema_bounds_payment_method():
    assert CustomerPaymentIn(amount="1.00", payment_method="cash").payment_method == "cash"
    with pytest.raises(ValidationError):
        CustomerPaymentIn(amount="1.00", payment_method="x" * 33)


def test_customer_payment_overflow_rejects_without_writes(client, auth_headers):
    customer_id = _customer_id()
    before = _write_counts()

    response = client.post(
        f"/api/customers/{customer_id}/payments",
        headers=auth_headers,
        json={"amount": "1000000000000.00"},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_customer_payment_subcent_precision_rejects_without_writes(client, auth_headers):
    customer_id = _customer_id()
    before = _write_counts()

    response = client.post(
        f"/api/customers/{customer_id}/payments",
        headers=auth_headers,
        json={"amount": "1.00000000000000001"},
    )

    assert response.status_code == 422, response.text
    assert _write_counts() == before


def test_customer_payment_rejects_unrepresentable_reference_or_method_without_writes(client, auth_headers):
    customer_id = _customer_id()
    before = _write_counts()

    for payload in (
        {"amount": "1.00", "sales_order_id": 2_147_483_648},
        {"amount": "1.00", "payment_method": "x" * 33},
    ):
        response = client.post(
            f"/api/customers/{customer_id}/payments",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 422, response.text
        assert _write_counts() == before


def test_customer_payment_path_id_is_int4_bounded_and_preserves_authentication(client, auth_headers):
    response = client.post("/api/customers/2147483648/payments", json={"amount": "1.00"})
    assert response.status_code == 401

    response = client.post(
        "/api/customers/2147483648/payments",
        headers=auth_headers,
        json={"amount": "1.00"},
    )
    assert response.status_code == 422, response.text


def test_customer_payment_maximum_persists_exactly(client, auth_headers):
    customer_id = _customer_id()

    response = client.post(
        f"/api/customers/{customer_id}/payments",
        headers=auth_headers,
        json={"amount": str(MAX_PAYMENT)},
    )

    assert response.status_code == 201, response.text
    payment_id = int(response.json()["id"])
    with TestSessionLocal() as db:
        assert db.get(Payment, payment_id).amount == MAX_PAYMENT


def test_customer_payment_overflow_preserves_authentication_precedence(client):
    customer_id = _customer_id()
    before = _write_counts()

    response = client.post(
        f"/api/customers/{customer_id}/payments",
        json={"amount": "1000000000000.00"},
    )

    assert response.status_code == 401, response.text
    assert _write_counts() == before
