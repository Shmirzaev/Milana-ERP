from uuid import uuid4


def _find_model_id(client, headers) -> int:
    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "Seed data should include at least one model"
    return int(rows[0]["id"])


def _create_customer(client, headers) -> int:
    suffix = uuid4().hex[:8]
    r = client.post(
        "/api/customers",
        json={
            "name": f"Payment Profile {suffix}",
            "phone": "+998900000002",
            "email": f"profile-{suffix}@example.com",
            "address": "Tashkent",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_sales_order(client, headers, *, customer_id: int, model_id: int, unit_price: float) -> dict:
    r = client.post(
        "/api/sales-orders",
        json={
            "customer_id": customer_id,
            "order_type": "client_order",
            "items": [
                {
                    "model_id": model_id,
                    "color": "white",
                    "size": "46",
                    "quantity": 1,
                    "unit_price": unit_price,
                }
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_invoice(client, headers, sales_order_id: int) -> dict:
    r = client.post("/api/finance/invoices", json={"sales_order_id": sales_order_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _create_payment(client, headers, *, invoice_id: int, amount: float) -> dict:
    r = client.post(
        "/api/finance/payments",
        json={"invoice_id": invoice_id, "amount": amount, "payment_method": "cash"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_customer_order_history_includes_invoice_and_payment_status(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    customer_id = _create_customer(client, auth_headers)

    no_invoice_order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=90,
    )
    unpaid_order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=100,
    )
    partial_order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=120,
    )
    paid_order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=140,
    )

    _create_invoice(client, auth_headers, int(unpaid_order["id"]))
    partial_invoice = _create_invoice(client, auth_headers, int(partial_order["id"]))
    paid_invoice = _create_invoice(client, auth_headers, int(paid_order["id"]))
    partial_payment = _create_payment(client, auth_headers, invoice_id=int(partial_invoice["id"]), amount=40)
    _create_payment(client, auth_headers, invoice_id=int(paid_invoice["id"]), amount=140)

    r = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = {int(row["id"]): row for row in r.json()}

    assert rows[int(no_invoice_order["id"])]["payment_status"] == "no_invoice"
    assert rows[int(no_invoice_order["id"])]["invoices"] == []
    assert rows[int(no_invoice_order["id"])]["balance_due"] == 90

    assert rows[int(unpaid_order["id"])]["payment_status"] == "unpaid"
    assert rows[int(unpaid_order["id"])]["paid_total"] == 0
    assert rows[int(unpaid_order["id"])]["balance_due"] == 100

    partial_row = rows[int(partial_order["id"])]
    assert partial_row["payment_status"] == "partial"
    assert partial_row["paid_total"] == 40
    assert partial_row["balance_due"] == 80
    assert partial_row["invoices"][0]["payments"][0]["id"] == partial_payment["id"]

    paid_row = rows[int(paid_order["id"])]
    assert paid_row["payment_status"] == "paid"
    assert paid_row["paid_total"] == 140
    assert paid_row["balance_due"] == 0

    r = client.get(f"/api/customers/{customer_id}/payments", headers=auth_headers)
    assert r.status_code == 200, r.text
    payments = r.json()
    assert any(row["id"] == partial_payment["id"] for row in payments)
    partial_payment_row = next(row for row in payments if row["id"] == partial_payment["id"])
    assert partial_payment_row["order_no"] == partial_order["order_no"]
    assert partial_payment_row["invoice_no"] == partial_invoice["invoice_no"]
    assert partial_payment_row["amount"] == 40
