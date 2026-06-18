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
    assert float(data1["revenue_total"]) >= 1000.0
    assert float(data1["payments_received"]) >= 300.0

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
    assert float(data2["revenue_total"]) >= 1000.0
    assert float(data2["payments_received"]) >= 1000.0


def _admin_token(client) -> str:
    r = client.post("/api/auth/token", data={"username": "admin@example.com", "password": "test-admin-password-123!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]
