from uuid import uuid4

import pytest

from app.models import Customer, Invoice, SalesOrder
from app.tests.conftest import TestSessionLocal


SYNC_URL = "/api/finance/integrations/1c/sync"
SYNC_HEADERS = {"X-1C-Token": "test-1c-token"}
VALID_STATUSES = ("unpaid", "partially_paid", "paid", "void", "cancelled")


def _order(marker: str) -> int:
    with TestSessionLocal() as db:
        customer = Customer(name=f"1C status customer {marker}")
        db.add(customer)
        db.flush()
        order = SalesOrder(
            order_no=f"1C-STATUS-{marker}",
            customer_id=customer.id,
            total_amount=100,
        )
        db.add(order)
        db.commit()
        return int(order.id)


def _invoice_payload(marker: str, order_id: int, status: str, *, external_id: str | None = None) -> dict:
    return {
        "external_id": external_id or f"invoice-{marker}",
        "sales_order_id": order_id,
        "invoice_no": f"1C-{marker}",
        "amount": 100,
        "status": status,
    }


@pytest.mark.parametrize("status", VALID_STATUSES)
def test_1c_invoice_sync_accepts_established_status_vocabulary(client, status):
    marker = uuid4().hex[:12]
    order_id = _order(marker)

    response = client.post(
        SYNC_URL,
        headers=SYNC_HEADERS,
        json={"invoices": [_invoice_payload(marker, order_id, status)], "payments": []},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "invoices_created": 1,
        "invoices_updated": 0,
        "payments_created": 0,
        "payments_updated": 0,
        "errors": [],
    }
    with TestSessionLocal() as db:
        invoice = db.query(Invoice).filter_by(external_source="1c", external_id=f"invoice-{marker}").one()
        assert invoice.status == status


def test_1c_invoice_sync_rejects_invalid_status_without_writing_that_row(client):
    marker = uuid4().hex[:12]
    order_id = _order(marker)
    good_marker = f"good-{marker}"
    bad_marker = f"bad-{marker}"

    response = client.post(
        SYNC_URL,
        headers=SYNC_HEADERS,
        json={
            "invoices": [
                _invoice_payload(good_marker, order_id, "unpaid"),
                _invoice_payload(bad_marker, order_id, "write_off"),
            ],
            "payments": [],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["invoices_created"] == 1
    assert body["invoices_updated"] == 0
    assert body["errors"] == [{
        "type": "invoice",
        "index": 1,
        "external_id": f"invoice-{bad_marker}",
        "error": "invalid invoice status; expected one of: cancelled, paid, partially_paid, unpaid, void",
    }]
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_source="1c", external_id=f"invoice-{good_marker}").count() == 1
        assert db.query(Invoice).filter_by(external_source="1c", external_id=f"invoice-{bad_marker}").count() == 0


def test_1c_invoice_sync_invalid_status_rolls_back_existing_invoice_update(client):
    marker = uuid4().hex[:12]
    order_id = _order(marker)
    external_id = f"invoice-{marker}"
    with TestSessionLocal() as db:
        invoice = Invoice(
            sales_order_id=order_id,
            invoice_no=f"1C-ORIGINAL-{marker}",
            amount=100,
            status="unpaid",
            external_source="1c",
            external_id=external_id,
        )
        db.add(invoice)
        db.commit()
        invoice_id = int(invoice.id)

    payload = _invoice_payload(marker, order_id, "write_off", external_id=external_id)
    payload.update({"invoice_no": f"1C-CHANGED-{marker}", "amount": 999})
    response = client.post(SYNC_URL, headers=SYNC_HEADERS, json={"invoices": [payload], "payments": []})

    assert response.status_code == 200, response.text
    assert response.json()["invoices_updated"] == 0
    assert response.json()["errors"][0]["error"].startswith("invalid invoice status;")
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, invoice_id)
        assert invoice.invoice_no == f"1C-ORIGINAL-{marker}"
        assert float(invoice.amount) == 100
        assert invoice.status == "unpaid"


def test_1c_invoice_sync_preserves_missing_order_error_precedence(client):
    marker = uuid4().hex[:12]
    response = client.post(
        SYNC_URL,
        headers=SYNC_HEADERS,
        json={"invoices": [_invoice_payload(marker, 2**40, "write_off")], "payments": []},
    )

    assert response.status_code == 200, response.text
    error = response.json()["errors"][0]
    assert error["error"] == "sales order not found (provide sales_order_id or sales_order_no)"
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_source="1c", external_id=f"invoice-{marker}").count() == 0


def test_1c_invoice_sync_checks_token_before_invalid_status_mutation(client):
    marker = uuid4().hex[:12]
    order_id = _order(marker)

    response = client.post(
        SYNC_URL,
        json={"invoices": [_invoice_payload(marker, order_id, "write_off")], "payments": []},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid 1C token"}
    with TestSessionLocal() as db:
        assert db.query(Invoice).filter_by(external_source="1c", external_id=f"invoice-{marker}").count() == 0
