def test_1c_sync_requires_token(client):
    r = client.post("/api/finance/integrations/1c/sync", json={"invoices": [], "payments": []})
    assert r.status_code == 401


def test_1c_sync_creates_and_updates_finance_data(client):
    headers = {"X-1C-Token": "test-1c-token"}

    payload_1 = {
        "invoices": [
            {
                "external_id": "inv-1c-1001",
                "sales_order_no": "SO-2025-000001",
                "invoice_no": "1C-INV-1001",
                "amount": 1000.0,
                "status": "unpaid",
            }
        ],
        "payments": [
            {
                "external_id": "pay-1c-7001",
                "invoice_external_id": "inv-1c-1001",
                "amount": 300.0,
                "payment_method": "bank_transfer",
            }
        ],
    }
    r1 = client.post("/api/finance/integrations/1c/sync", json=payload_1, headers=headers)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["invoices_created"] == 1
    assert body1["payments_created"] == 1
    assert body1["errors"] == []

    dashboard1 = client.get("/api/finance/dashboard", headers={"Authorization": "Bearer " + _admin_token(client)})
    assert dashboard1.status_code == 200
    data1 = dashboard1.json()
    assert data1["revenue_total"] is None
    assert data1["payments_received"] is None

    payload_2 = {
        "invoices": [
            {
                "external_id": "inv-1c-1001",
                "sales_order_no": "SO-2025-000001",
                "invoice_no": "1C-INV-1001",
                "amount": 1000.0,
                "status": "partially_paid",
            }
        ],
        "payments": [
            {
                "external_id": "pay-1c-7001",
                "invoice_external_id": "inv-1c-1001",
                "amount": 1000.0,
                "payment_method": "bank_transfer",
            }
        ],
    }
    r2 = client.post("/api/finance/integrations/1c/sync", json=payload_2, headers=headers)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["invoices_updated"] == 1
    assert body2["payments_updated"] == 1
    assert body2["errors"] == []

    dashboard2 = client.get("/api/finance/dashboard", headers={"Authorization": "Bearer " + _admin_token(client)})
    assert dashboard2.status_code == 200
    data2 = dashboard2.json()
    assert data2["revenue_total"] is None
    assert data2["payments_received"] is None


def _admin_token(client) -> str:
    r = client.post("/api/auth/token", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Invoice, Payment


def test_1c_payment_sync_preserves_void_and_cancelled_invoice_states(client):
    terminal_invoice_id = f"fn07-terminal-invoice-{uuid4().hex}"
    active_invoice_id = f"fn07-active-invoice-{uuid4().hex}"
    blocked_payment_id = f"fn07-blocked-payment-{uuid4().hex}"
    active_payment_id = f"fn07-active-payment-{uuid4().hex}"
    headers = {"X-1C-Token": "test-1c-token"}

    def sync(terminal_status, active_status="unpaid", active_amount="100.00"):
        return client.post("/api/finance/integrations/1c/sync", headers=headers, json={
            "invoices": [{
                "external_id": terminal_invoice_id,
                "sales_order_no": "SO-2025-000001",
                "invoice_no": terminal_invoice_id,
                "amount": "100.00",
                "status": terminal_status,
            }, {
                "external_id": active_invoice_id,
                "sales_order_no": "SO-2025-000001",
                "invoice_no": active_invoice_id,
                "amount": "100.00",
                "status": active_status,
            }],
            "payments": [{
                "external_id": blocked_payment_id,
                "invoice_external_id": terminal_invoice_id,
                "amount": "100.00",
            }, {
                "external_id": active_payment_id,
                "invoice_external_id": active_invoice_id,
                "amount": active_amount,
            }],
        })

    first = sync("void")
    assert first.status_code == 200, first.text
    assert len(first.json()["errors"]) == 1
    assert first.json()["errors"][0]["index"] == 0
    assert "void or cancelled" in first.json()["errors"][0]["error"]
    assert first.json()["payments_created"] == 1
    with SessionLocal() as db:
        terminal = db.query(Invoice).filter_by(external_source="1c", external_id=terminal_invoice_id).one()
        active = db.query(Invoice).filter_by(external_source="1c", external_id=active_invoice_id).one()
        assert terminal.status == "void" and active.status == "paid"
        assert db.query(Payment).filter_by(external_source="1c", external_id=blocked_payment_id).count() == 0
        assert db.query(Payment).filter_by(external_source="1c", external_id=active_payment_id).one().amount == 100

    second = sync("cancelled", active_amount="50.00")
    assert second.status_code == 200, second.text
    assert len(second.json()["errors"]) == 1
    assert second.json()["errors"][0]["index"] == 0
    assert second.json()["payments_updated"] == 1
    with SessionLocal() as db:
        terminal = db.query(Invoice).filter_by(external_source="1c", external_id=terminal_invoice_id).one()
        active = db.query(Invoice).filter_by(external_source="1c", external_id=active_invoice_id).one()
        assert terminal.status == "cancelled" and active.status == "partially_paid"
        assert db.query(Payment).filter_by(external_source="1c", external_id=blocked_payment_id).count() == 0
        assert db.query(Payment).filter_by(external_source="1c", external_id=active_payment_id).one().amount == 50

    third = sync("cancelled", active_status="cancelled", active_amount="80.00")
    assert third.status_code == 200, third.text
    assert len(third.json()["errors"]) == 2
    assert third.json()["payments_updated"] == 0
    with SessionLocal() as db:
        active = db.query(Invoice).filter_by(external_source="1c", external_id=active_invoice_id).one()
        assert active.status == "cancelled"
        assert db.query(Payment).filter_by(external_source="1c", external_id=active_payment_id).one().amount == 50

    reassignment = client.post("/api/finance/integrations/1c/sync", headers=headers, json={
        "invoices": [],
        "payments": [{
            "external_id": active_payment_id,
            "invoice_external_id": terminal_invoice_id,
            "amount": "80.00",
        }],
    })
    assert reassignment.status_code == 200, reassignment.text
    assert reassignment.json()["payments_updated"] == 0
    assert len(reassignment.json()["errors"]) == 1
    with SessionLocal() as db:
        active = db.query(Invoice).filter_by(external_source="1c", external_id=active_invoice_id).one()
        payment = db.query(Payment).filter_by(external_source="1c", external_id=active_payment_id).one()
        assert payment.invoice_id == active.id
        assert payment.amount == 50
