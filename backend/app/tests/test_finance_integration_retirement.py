"""Retire the unused connector while preserving historical and manual finance."""

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.main import app
from app.models import AuditLog, Invoice, Payment, SalesOrder
from app.tests.conftest import TestSessionLocal


@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("supplied_token", [False, True])
def test_retired_sync_is_missing_and_cannot_write(client, auth_headers, authenticated, supplied_token):
    with TestSessionLocal() as db:
        before = [db.query(model).count() for model in (Invoice, Payment, AuditLog)]
    headers = {"X-1C-Token": "obsolete-token"} if supplied_token else {}
    if authenticated:
        headers.update(auth_headers)
    response = client.post("/api/finance/integrations/1c/sync", headers=headers,
                           json={"invoices": [{"external_id": "obsolete", "amount": 12}], "payments": []})
    assert response.status_code == 404, response.text
    assert not any("/integrations/1c" in path for path in app.openapi()["paths"])
    assert not any(name.startswith("OneC") for name in app.openapi()["components"]["schemas"])
    with TestSessionLocal() as db:
        assert [db.query(model).count() for model in (Invoice, Payment, AuditLog)] == before


def test_strict_security_needs_no_retired_credentials(monkeypatch):
    monkeypatch.setenv("INTEGRATION_1C_CLIENTS_JSON", "malformed obsolete value")
    monkeypatch.setenv("INTEGRATION_1C_TOKEN", "unused")
    config = Settings(_env_file=None, ENV="production", DEBUG=False,
                      JWT_SECRET="j" * 48, FILE_SIGNING_SECRET="f" * 48,
                      DATABASE_URL="postgresql://finance:example@localhost/finance",
                      CORS_ORIGINS="https://erp.example.test", SHARED_STORE_URL="redis://localhost:6379")
    config.validate_runtime_security()
    assert config.strict_security_required
    assert not any(field.startswith("INTEGRATION_1C") for field in Settings.model_fields)
    assert "ATTENDANCE_INTEGRATION_TOKEN" in Settings.model_fields


def test_historical_import_origin_survives_manual_payment(client, auth_headers):
    with TestSessionLocal() as db:
        order = SalesOrder(order_no="SO-RETIRED-CONNECTOR", total_amount=50)
        db.add(order)
        db.flush()
        invoice = Invoice(sales_order_id=order.id, invoice_no="HISTORICAL-IMPORT",
                          amount=50, status="partially_paid", external_source="1c", external_id="old-invoice")
        db.add(invoice)
        db.flush()
        historical = Payment(invoice_id=invoice.id, amount=20,
                             external_source="1c", external_id="old-payment")
        db.add(historical)
        db.commit()
        invoice_id, historical_id = invoice.id, historical.id
    response = client.get("/api/finance/invoices", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert any(row["id"] == invoice_id for row in response.json())
    response = client.post("/api/finance/payments", headers={**auth_headers, "Idempotency-Key": "retirement-manual-payment"},
                           json={"invoice_id": invoice_id, "amount": 30, "payment_method": "cash"})
    assert response.status_code == 201, response.text
    repeat = client.post("/api/finance/payments", headers={**auth_headers, "Idempotency-Key": "retirement-manual-payment"},
                         json={"invoice_id": invoice_id, "amount": 30, "payment_method": "cash"})
    assert repeat.json()["id"] == response.json()["id"]
    with TestSessionLocal() as db:
        invoice, historical = db.get(Invoice, invoice_id), db.get(Payment, historical_id)
        assert (invoice.external_source, invoice.external_id, invoice.status) == ("1c", "old-invoice", "paid")
        assert (historical.external_source, historical.external_id, historical.amount) == ("1c", "old-payment", Decimal("20"))
        assert db.query(Payment).filter_by(invoice_id=invoice_id).count() == 2


@pytest.mark.parametrize("amount,status", [(0, "paid"), (1, "paid"), (1.01, "unpaid")])
def test_new_manual_invoice_uses_approved_settlement_status_without_payment(client, auth_headers, amount, status):
    with TestSessionLocal() as db:
        order = SalesOrder(order_no=f"SO-SETTLEMENT-{amount}", total_amount=amount)
        db.add(order)
        db.commit()
        order_id = order.id
    response = client.post("/api/finance/invoices", headers=auth_headers,
                           json={"sales_order_id": order_id, "amount": amount})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == status
    with TestSessionLocal() as db:
        invoice = db.get(Invoice, response.json()["id"])
        assert invoice.amount == Decimal(str(amount))
        assert invoice.status == status
        assert db.query(Payment).filter_by(invoice_id=invoice.id).count() == 0
