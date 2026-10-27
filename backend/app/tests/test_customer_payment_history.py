import re
from uuid import uuid4


def _find_model_id(client, headers) -> int:
    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "Seed data should include at least one model"
    approved = next((row for row in rows if row.get("status") == "approved"), None)
    assert approved, "Seed data should include at least one approved model"
    return int(approved["id"])


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


def _create_customer_payment(client, headers, *, customer_id: int, amount: float, sales_order_id: int | None = None) -> dict:
    payload = {"amount": amount, "payment_method": "cash"}
    if sales_order_id is not None:
        payload["sales_order_id"] = sales_order_id
    r = client.post(
        f"/api/customers/{customer_id}/payments",
        json=payload,
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


def test_sales_order_history_endpoint_returns_order_ledger(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    customer_id = _create_customer(client, auth_headers)
    order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=100,
    )
    invoice = _create_invoice(client, auth_headers, int(order["id"]))
    payment = _create_payment(client, auth_headers, invoice_id=int(invoice["id"]), amount=35)

    r = client.get(
        f"/api/sales-orders/history?include_total=true&page_size=10&q={order['order_no']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = [row for row in r.json()["rows"] if int(row["id"]) == int(order["id"])]
    assert rows, r.json()
    row = rows[0]
    assert row["customer_name"]
    assert row["summary"]["ordered_qty"] == 1
    assert row["summary"]["order_amount"] == 100
    assert row["summary"]["paid_total"] == 35
    assert row["summary"]["outstanding_amount"] == 65
    assert row["summary"]["invoice_count"] == 1
    assert row["summary"]["payment_count"] == 1

    detail = client.get(f"/api/sales-orders/{order['id']}/history", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["order_no"] == order["order_no"]
    assert payload["items"][0]["quantity"] == 1
    assert payload["items"][0]["line_total"] == 100
    assert payload["invoices"][0]["invoice_no"] == invoice["invoice_no"]
    assert payload["payments"][0]["id"] == payment["id"]
    assert any(event["type"] == "order_created" for event in payload["timeline"])
    assert any(event["type"] == "payment" for event in payload["timeline"])


def test_order_history_includes_planning_created_stock_orders(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    created = client.post(
        "/api/planning/create-branded-production",
        headers=auth_headers,
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 12,
            "estimated_material_code": "FAB-STOCK",
            "estimated_material_amount": 4.5,
            "estimated_material_unit": "kg",
            "printing_instructions": "Front logo",
            "items": [
                {
                    "model_id": model_id,
                    "color": "Black",
                    "size": "M",
                    "planned_quantity": 12,
                    "printing_required": True,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    production = created.json()

    history = client.get(
        f"/api/sales-orders/history?include_total=true&q={production['production_no']}",
        headers=auth_headers,
    )
    assert history.status_code == 200, history.text
    row = next(item for item in history.json()["rows"] if item["history_key"] == f"production:{production['id']}")
    assert row["record_type"] == "production_order"
    assert row["order_type"] == "branded_stock"
    assert row["summary"]["ordered_qty"] == 12

    detail = client.get(f"/api/sales-orders/history/production/{production['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["production_orders"][0]["estimated_material_code"] == "FAB-STOCK"
    assert payload["production_orders"][0]["printing_instructions"] == "Front logo"
    assert payload["items"][0]["color"] == "Black"
    assert payload["production_orders"][0]["work_orders"]
    assert "cutting" in payload["step_records"]
    assert "material_reservations" in payload["step_records"]


def test_branded_planning_order_groups_multiple_productions_and_is_searchable(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    created_order = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": "besttex"},
    )
    assert created_order.status_code == 201, created_order.text
    planning_order = created_order.json()
    assert re.fullmatch(r"\d{4,}", planning_order["order_no"])
    assert planning_order["ordered_for_name"] == "Besttex"

    next_order = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={},
    )
    assert next_order.status_code == 201, next_order.text
    assert int(next_order.json()["order_no"]) == int(planning_order["order_no"]) + 1
    assert next_order.json()["ordered_for_name"] == "Milana"

    production_ids = []
    for color in ("Black", "White"):
        created = client.post(
            "/api/planning/create-branded-production",
            headers=auth_headers,
            json={
                "production_type": "branded_stock",
                "planning_order_id": planning_order["id"],
                "model_id": model_id,
                "planned_quantity": 10,
                "items": [
                    {
                        "model_id": model_id,
                        "color": color,
                        "size": "M",
                        "planned_quantity": 10,
                    }
                ],
            },
        )
        assert created.status_code == 201, created.text
        production_ids.append(int(created.json()["id"]))

    grouped = client.get("/api/planning/branded-orders", headers=auth_headers)
    assert grouped.status_code == 200, grouped.text
    group = next(row for row in grouped.json() if int(row["id"]) == int(planning_order["id"]))
    assert group["production_count"] == 2
    assert group["total_quantity"] == 20

    history = client.get(
        f"/api/sales-orders/history?include_total=true&q={planning_order['order_no']}",
        headers=auth_headers,
    )
    assert history.status_code == 200, history.text
    assert all(row["group_order_no"] == planning_order["order_no"] for row in history.json()["rows"])
    rows = [
        row for row in history.json()["rows"]
        if row["record_type"] == "production_order" and int(row["id"]) in production_ids
    ]
    assert len(rows) == 2
    assert all(row["group_order_no"] == planning_order["order_no"] for row in rows)
    assert all(row["ordered_for"] == "Besttex" for row in rows)


def test_branded_order_history_includes_linked_model_metadata_when_picker_excludes_it(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    model_code = f"HISTORY-{suffix}"
    model_image_url = f"/storage/model-files/history-model-{suffix}.jpg"
    fabric_image_url = f"/storage/model-files/history-fabric-{suffix}.jpg"
    created_model = client.post(
        "/api/models",
        headers=auth_headers,
        json={
            "code": model_code,
            "name": "Historical linked model",
            "status": "approved",
            "details_json": {
                "legacy_import": True,
                "general": {"variant_fabric": "History fabric / Navy"},
            },
        },
    )
    assert created_model.status_code == 201, created_model.text
    model_id = int(created_model.json()["id"])

    for image_type, file_url, is_primary in (
        ("model", model_image_url, True),
        ("material", fabric_image_url, False),
    ):
        image = client.post(
            f"/api/models/{model_id}/images",
            headers=auth_headers,
            json={
                "file_url": file_url,
                "file_name": file_url.rsplit("/", 1)[-1],
                "content_type": "image/jpeg",
                "image_type": image_type,
                "is_primary": is_primary,
            },
        )
        assert image.status_code == 201, image.text

    picker = client.get("/api/models?status=approved", headers=auth_headers)
    assert picker.status_code == 200, picker.text
    assert all(int(row["id"]) != model_id for row in picker.json())

    planning_order = client.post(
        "/api/planning/branded-orders",
        headers=auth_headers,
        json={"ordered_for_type": "milana"},
    )
    assert planning_order.status_code == 201, planning_order.text
    production = client.post(
        "/api/planning/create-branded-production",
        headers=auth_headers,
        json={
            "production_type": "branded_stock",
            "planning_order_id": planning_order.json()["id"],
            "model_id": model_id,
            "planned_quantity": 10,
            "items": [
                {"model_id": model_id, "color": "Navy", "size": "M", "planned_quantity": 10},
            ],
        },
    )
    assert production.status_code == 201, production.text

    history = client.get("/api/planning/branded-orders", headers=auth_headers)
    assert history.status_code == 200, history.text
    group = next(row for row in history.json() if int(row["id"]) == int(planning_order.json()["id"]))
    linked_model = group["productions"][0]["model"]
    assert linked_model == {
        "id": model_id,
        "code": model_code,
        "name": "Historical linked model",
        "primary_image_url": model_image_url,
        "variant_fabric": "History fabric / Navy",
        "fabric_image_url": fabric_image_url,
    }


def test_customer_profile_payment_persists_and_updates_order_status(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    customer_id = _create_customer(client, auth_headers)
    order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=125,
    )

    payment = _create_customer_payment(
        client,
        auth_headers,
        customer_id=customer_id,
        sales_order_id=int(order["id"]),
        amount=50,
    )

    assert payment["order_id"] == order["id"]
    assert payment["order_no"] == order["order_no"]
    assert payment["invoice_no"].startswith("INV-")
    assert payment["invoice_id"] > 0
    assert payment["amount"] == 50

    r = client.get(f"/api/customers/{customer_id}/payments", headers=auth_headers)
    assert r.status_code == 200, r.text
    payments = r.json()
    assert any(row["id"] == payment["id"] for row in payments)

    r = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    saved_order = next(row for row in r.json() if int(row["id"]) == int(order["id"]))
    assert saved_order["payment_status"] == "partial"
    assert saved_order["paid_total"] == 50
    assert saved_order["balance_due"] == 75
    assert saved_order["invoices"][0]["payments"][0]["id"] == payment["id"]


def test_customer_profile_overpayment_becomes_advance_credit(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    customer_id = _create_customer(client, auth_headers)
    order = _create_sales_order(
        client,
        auth_headers,
        customer_id=customer_id,
        model_id=model_id,
        unit_price=3000,
    )

    payment = _create_customer_payment(
        client,
        auth_headers,
        customer_id=customer_id,
        sales_order_id=int(order["id"]),
        amount=43000,
    )

    assert payment["is_advance"] is True
    assert payment["amount"] == 40000
    assert payment["order_id"] is None
    assert payment["invoice_id"] is None

    r = client.get(f"/api/customers/{customer_id}/orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    saved_order = next(row for row in r.json() if int(row["id"]) == int(order["id"]))
    assert saved_order["payment_status"] == "paid"
    assert saved_order["paid_total"] == 3000
    assert saved_order["balance_due"] == 0
    assert saved_order["invoices"][0]["paid_amount"] == 3000
    assert saved_order["invoices"][0]["advance_amount"] == 0

    r = client.get(f"/api/customers/{customer_id}/payments", headers=auth_headers)
    assert r.status_code == 200, r.text
    payments = r.json()
    assert sum(row["amount"] for row in payments) == 43000
    assert any(row["amount"] == 3000 and row["order_no"] == order["order_no"] for row in payments)
    assert any(row["amount"] == 40000 and row["is_advance"] is True and row["order_id"] is None for row in payments)


def test_customer_profile_accepts_advance_payment_without_order(client, auth_headers):
    customer_id = _create_customer(client, auth_headers)

    payment = _create_customer_payment(
        client,
        auth_headers,
        customer_id=customer_id,
        amount=40000,
    )

    assert payment["is_advance"] is True
    assert payment["amount"] == 40000
    assert payment["order_id"] is None
    assert payment["order_no"] is None
    assert payment["invoice_id"] is None
    assert payment["invoice_no"] is None

    r = client.get(f"/api/customers/{customer_id}/payments", headers=auth_headers)
    assert r.status_code == 200, r.text
    payments = r.json()
    assert len(payments) == 1
    assert payments[0]["id"] == payment["id"]
    assert payments[0]["is_advance"] is True


def test_customer_profile_payment_rejects_order_from_another_customer(client, auth_headers):
    model_id = _find_model_id(client, auth_headers)
    customer_id = _create_customer(client, auth_headers)
    other_customer_id = _create_customer(client, auth_headers)
    other_order = _create_sales_order(
        client,
        auth_headers,
        customer_id=other_customer_id,
        model_id=model_id,
        unit_price=80,
    )

    r = client.post(
        f"/api/customers/{customer_id}/payments",
        json={"sales_order_id": other_order["id"], "amount": 80, "payment_method": "cash"},
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text

    r = client.post(
        f"/api/customers/{customer_id}/payments",
        json={"amount": 80, "payment_method": "cash"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["is_advance"] is True
