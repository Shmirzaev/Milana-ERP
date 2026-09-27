"""Validate 1C money before PostgreSQL NUMERIC writes."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models import Customer, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal


SYNC_URL = "/api/finance/integrations/1c/sync"
SYNC_HEADERS = {"X-1C-Token": "test-1c-token"}
MAX_MONEY = 999_999_999_999.99


def _order_and_invoice(marker: str) -> tuple[int, int]:
    with TestSessionLocal() as db:
        customer = Customer(name=f"1C amount customer {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(order_no=f"1C-AMOUNT-{marker}", customer_id=customer.id, total_amount=100)
        db.add(order)
        db.flush()
        invoice = Invoice(
            sales_order_id=order.id,
            invoice_no=f"1C-AMOUNT-BASE-{marker}",
            amount=100,
            status="unpaid",
            external_source="1c",
            external_id=f"base-{marker}",
        )
        db.add(invoice)
        db.commit()
        return int(order.id), int(invoice.id)


@pytest.mark.parametrize(
    ("kind", "amount"),
    [("invoice", 0), ("invoice", MAX_MONEY), ("payment", 0.01), ("payment", MAX_MONEY)],
)
def test_1c_sync_accepts_established_money_boundaries(client, kind, amount):
    marker = uuid4().hex[:12]
    order_id, invoice_id = _order_and_invoice(marker)
    external_id = f"{kind}-{marker}"
    row = {"external_id": external_id, "amount": amount}
    if kind == "invoice":
        row["sales_order_id"] = order_id
        payload = {"invoices": [row]}
    else:
        row["invoice_id"] = invoice_id
        payload = {"payments": [row]}

    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["errors"] == []
    with TestSessionLocal() as db:
        model = Invoice if kind == "invoice" else Payment
        stored = db.query(model).filter_by(external_source="1c", external_id=external_id).one()
        assert stored.amount == Decimal(str(amount))


@pytest.mark.parametrize(
    ("kind", "amount", "error"),
    [
        ("invoice", -0.01, "invoice amount must be nonnegative"),
        ("invoice", float("nan"), "invoice amount must be finite"),
        ("invoice", float("inf"), "invoice amount must be finite"),
        ("invoice", 1_000_000_000_000, "invoice amount must be no more than 999999999999.99"),
        ("payment", 0, "payment amount must be greater than zero"),
        ("payment", -0.01, "payment amount must be greater than zero"),
        ("invoice", 1.001, "invoice amount must have at most 2 decimal places"),
        ("payment", 1.001, "payment amount must have at most 2 decimal places"),
        ("payment", float("nan"), "payment amount must be finite"),
        ("payment", float("inf"), "payment amount must be finite"),
        ("payment", 1_000_000_000_000, "payment amount must be no more than 999999999999.99"),
    ],
)
def test_1c_sync_isolates_invalid_amount_and_keeps_valid_sibling(client, kind, amount, error):
    marker = uuid4().hex[:12]
    order_id, invoice_id = _order_and_invoice(marker)
    good_external_id = f"good-{kind}-{marker}"
    bad_external_id = f"bad-{kind}-{marker}"
    if kind == "invoice":
        common = {"sales_order_id": order_id}
        payload = {"invoices": [
            {"external_id": good_external_id, "amount": 10, **common},
            {"external_id": bad_external_id, "amount": amount, **common},
        ]}
    else:
        common = {"invoice_id": invoice_id}
        payload = {"payments": [
            {"external_id": good_external_id, "amount": 5, **common},
            {"external_id": bad_external_id, "amount": amount, **common},
        ]}

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
def test_1c_sync_preserves_missing_reference_before_amount_error(client, kind):
    if kind == "invoice":
        payload = {"invoices": [{"external_id": "bad-invoice", "sales_order_id": 2**40, "amount": -1}]}
        expected = "sales order not found (provide sales_order_id or sales_order_no)"
    else:
        payload = {"payments": [{"external_id": "bad-payment", "invoice_id": 2**40, "amount": 0}]}
        expected = "invoice not found (provide invoice_id, invoice_no, or invoice_external_id)"

    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["errors"][0]["error"] == expected


def test_1c_sync_preserves_status_and_token_precedence_for_invalid_amount(client):
    marker = uuid4().hex[:12]
    order_id, _ = _order_and_invoice(marker)
    row = {"external_id": f"bad-{marker}", "sales_order_id": order_id, "amount": -1, "status": "write_off"}

    unauthorized = client.post(SYNC_URL, json={"invoices": [row]})
    invalid = client.post(SYNC_URL, headers=SYNC_HEADERS, json={"invoices": [row]})

    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Invalid 1C token"}
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["errors"][0]["error"].startswith("invalid invoice status;")
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_id=f"bad-{marker}").count() == 0
