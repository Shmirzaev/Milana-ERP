from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import AuditLog, Customer, Invoice, Payment, SalesOrder


PAYMENTS_URL = "/api/finance/payments"


def _payment_case(*, with_invoice: bool = True) -> tuple[int, int, int | None]:
    marker = uuid4().hex
    with SessionLocal() as db:
        customer = Customer(name=f"Payment method {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"PAYMENT-METHOD-{marker}",
            customer_id=customer.id,
            total_amount=100,
        )
        db.add(order)
        db.flush()
        invoice = None
        if with_invoice:
            invoice = Invoice(
                sales_order_id=order.id,
                invoice_no=f"PAYMENT-METHOD-{marker}",
                amount=100,
                status="unpaid",
            )
            db.add(invoice)
        db.commit()
        return int(customer.id), int(order.id), int(invoice.id) if invoice else None


@pytest.mark.parametrize("payment_method", ["bank_transfer", "cash", "card"])
def test_manual_invoice_payment_accepts_ui_payment_methods(client, auth_headers, payment_method):
    _, _, invoice_id = _payment_case()

    response = client.post(
        PAYMENTS_URL,
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": 10, "payment_method": payment_method},
    )

    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] == payment_method
    with SessionLocal() as db:
        payment = db.get(Payment, response.json()["id"])
        assert payment.payment_method == payment_method


def test_manual_invoice_payment_keeps_omitted_method_compatible(client, auth_headers):
    _, _, invoice_id = _payment_case()

    response = client.post(
        PAYMENTS_URL,
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": 10},
    )

    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] is None


def test_manual_invoice_payment_rejects_unknown_method_without_mutation(client, auth_headers):
    _, _, invoice_id = _payment_case()
    with SessionLocal() as db:
        before_payments = db.query(Payment).count()
        before_audits = db.query(AuditLog).count()

    response = client.post(
        PAYMENTS_URL,
        headers=auth_headers,
        json={"invoice_id": invoice_id, "amount": 10, "payment_method": "crypto"},
    )

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": "Invalid payment_method; expected bank_transfer, cash, or card"
    }
    with SessionLocal() as db:
        assert db.query(Payment).count() == before_payments
        assert db.query(AuditLog).count() == before_audits
        assert db.get(Invoice, invoice_id).status == "unpaid"


def test_customer_payment_invalid_method_rolls_back_auto_created_invoice(client, auth_headers):
    customer_id, order_id, _ = _payment_case(with_invoice=False)
    with SessionLocal() as db:
        before_invoices = db.query(Invoice).count()
        before_payments = db.query(Payment).count()
        before_audits = db.query(AuditLog).count()

    response = client.post(
        f"/api/customers/{customer_id}/payments",
        headers=auth_headers,
        json={
            "sales_order_id": order_id,
            "amount": 10,
            "payment_method": "crypto",
        },
    )

    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": "Invalid payment_method; expected bank_transfer, cash, or card"
    }
    with SessionLocal() as db:
        assert db.query(Invoice).count() == before_invoices
        assert db.query(Payment).count() == before_payments
        assert db.query(AuditLog).count() == before_audits
        assert db.query(Invoice).filter_by(sales_order_id=order_id).count() == 0


def test_manual_payment_preserves_missing_resource_precedence(client, auth_headers):
    response = client.post(
        PAYMENTS_URL,
        headers=auth_headers,
        json={"invoice_id": 2_147_483_647, "amount": 10, "payment_method": "crypto"},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Invoice not found"}


def test_manual_payment_preserves_authentication_precedence(client):
    _, _, invoice_id = _payment_case()
    with SessionLocal() as db:
        before_payments = db.query(Payment).count()

    response = client.post(
        PAYMENTS_URL,
        json={"invoice_id": invoice_id, "amount": 10, "payment_method": "crypto"},
    )

    assert response.status_code == 401, response.text
    with SessionLocal() as db:
        assert db.query(Payment).count() == before_payments
        assert db.get(Invoice, invoice_id).status == "unpaid"
