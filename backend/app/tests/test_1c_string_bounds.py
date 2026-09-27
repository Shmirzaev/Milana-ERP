"""Keep 1C text values within their PostgreSQL finance columns."""

from uuid import uuid4

import pytest

from app.models import Customer, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal


SYNC_URL = "/api/finance/integrations/1c/sync"
SYNC_HEADERS = {"X-1C-Token": "test-1c-token"}


def _order_and_invoice(marker: str) -> tuple[int, int]:
    with TestSessionLocal() as db:
        customer = Customer(name=f"1C bounds customer {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"1C-BOUNDS-{marker}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"1C-BASE-{marker}",
            amount=100,
            status="unpaid",
            external_source="1c",
            external_id=f"base-{marker}",
        )
        db.add(invoice)
        db.commit()
        return int(order.id), int(invoice.id)


def test_1c_sync_accepts_exact_database_text_limits(client):
    marker = uuid4().hex[:12]
    order_id, invoice_id = _order_and_invoice(marker)
    invoice_external_id = f"i{marker}".ljust(128, "x")
    invoice_no = f"N{marker}".ljust(64, "x")
    payment_external_id = f"p{marker}".ljust(128, "x")
    payment_method = "m" * 32

    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json={
        "invoices": [{
            "external_id": invoice_external_id,
            "sales_order_id": order_id,
            "invoice_no": invoice_no,
            "amount": 10,
        }],
        "payments": [{
            "external_id": payment_external_id,
            "invoice_id": invoice_id,
            "amount": 5,
            "payment_method": payment_method,
        }],
    })

    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_id=invoice_external_id, invoice_no=invoice_no).count() == 1
        assert db.query(Payment).filter_by(external_id=payment_external_id, payment_method=payment_method).count() == 1


@pytest.mark.parametrize(
    ("kind", "field", "value", "error"),
    [
        ("invoice", "external_id", "x" * 129, "external_id must be at most 128 characters"),
        ("invoice", "invoice_no", "x" * 65, "invoice_no must be at most 64 characters"),
        ("payment", "external_id", "x" * 129, "external_id must be at most 128 characters"),
        ("payment", "payment_method", "x" * 33, "payment_method must be at most 32 characters"),
    ],
)
def test_1c_sync_rejects_oversized_row_and_keeps_valid_sibling(client, kind, field, value, error):
    marker = uuid4().hex[:12]
    order_id, invoice_id = _order_and_invoice(marker)
    if kind == "invoice":
        good_external_id = f"good-invoice-{marker}"
        good = {"external_id": good_external_id, "sales_order_id": order_id, "amount": 10}
        bad = {"external_id": f"bad-invoice-{marker}", "sales_order_id": order_id, "amount": 10, field: value}
        payload = {"invoices": [good, bad], "payments": []}
    else:
        good_external_id = f"good-payment-{marker}"
        good = {"external_id": good_external_id, "invoice_id": invoice_id, "amount": 5}
        bad = {"external_id": f"bad-payment-{marker}", "invoice_id": invoice_id, "amount": 5, field: value}
        payload = {"invoices": [], "payments": [good, bad]}
    bad_external_id = bad["external_id"]

    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["errors"] == [{
        "type": kind,
        "index": 1,
        "external_id": bad_external_id,
        "error": error,
    }]
    with TestSessionLocal() as db:
        model = Invoice if kind == "invoice" else Payment
        assert db.query(model).filter_by(external_source="1c", external_id=good_external_id).count() == 1
        assert db.query(model).filter_by(external_source="1c", external_id=bad_external_id).count() == 0


@pytest.mark.parametrize("kind", ["invoice", "payment"])
def test_1c_sync_preserves_missing_reference_before_text_bound_error(client, kind):
    marker = uuid4().hex[:12]
    if kind == "invoice":
        payload = {"invoices": [{"external_id": "x" * 129, "sales_order_id": 2**40, "amount": 10}]}
        expected = "sales order not found (provide sales_order_id or sales_order_no)"
    else:
        payload = {"payments": [{"external_id": "x" * 129, "invoice_id": 2**40, "amount": 10}]}
        expected = "invoice not found (provide invoice_id, invoice_no, or invoice_external_id)"

    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["errors"][0]["error"] == expected
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_id="x" * 129).count() == 0
        assert db.query(Payment).filter_by(external_id="x" * 129).count() == 0


def test_1c_sync_preserves_token_precedence_for_oversized_text(client):
    response = client.post(SYNC_URL, json={
        "invoices": [{"external_id": "x" * 129, "sales_order_id": 1, "amount": 10}],
    })

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid 1C token"}
