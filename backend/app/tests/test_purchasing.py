STRONG_PW = "PurchasingTest123!"


def _login(client, email: str, password: str = STRONG_PW) -> dict[str, str]:
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _department_id(client, headers, code: str) -> int:
    r = client.get("/api/departments", headers=headers)
    assert r.status_code == 200, r.text
    return int(next(row for row in r.json() if row["code"] == code)["id"])


def _create_user_with_permissions(
    client,
    admin_headers,
    *,
    email: str,
    permissions: list[str],
    department_code: str | None = None,
) -> dict[str, str]:
    role = client.post(
        "/api/roles",
        json={"name": f"Role {email}", "permissions": permissions},
        headers=admin_headers,
    )
    assert role.status_code == 201, role.text
    payload = {
        "name": email.split("@", 1)[0],
        "email": email,
        "password": STRONG_PW,
        "role_id": role.json()["id"],
        "is_active": True,
    }
    if department_code:
        payload["department_id"] = _department_id(client, admin_headers, department_code)
    user = client.post(
        "/api/users",
        json=payload,
        headers=admin_headers,
    )
    assert user.status_code == 201, user.text
    return _login(client, email)


def _create_large_sales_order(client, headers, quantity: int = 10000) -> int:
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "purchasing shortage test",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": quantity, "unit_price": 12.5},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    so_id = int(r.json()["id"])
    confirm = client.post(f"/api/sales-orders/{so_id}/confirm", headers=headers)
    assert confirm.status_code == 200, confirm.text
    return so_id


def _stock_quantity(client, headers, sku: str) -> float:
    r = client.get(f"/api/inventory/stock?group=materials&q={sku}", headers=headers)
    assert r.status_code == 200, r.text
    row = next(item for item in r.json() if item["item_sku"] == sku)
    return float(row["quantity"])


def _fabric_warehouse_id(client, headers) -> int:
    r = client.get("/api/inventory/warehouses", headers=headers)
    assert r.status_code == 200, r.text
    return int(next(row for row in r.json() if row["type"] == "fabric_storage")["id"])


def _first_supplier_id(client, headers) -> int:
    r = client.get("/api/suppliers", headers=headers)
    assert r.status_code == 200, r.text
    return int(r.json()[0]["id"])


def _item_by_sku(client, headers, sku: str) -> dict:
    r = client.get(f"/api/inventory/items?group=materials&q={sku}&page_size=50", headers=headers)
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["sku"] == sku)


def _create_approved_purchase_order(client, headers) -> dict:
    so_id = _create_large_sales_order(client, headers)
    request = client.post(f"/api/purchasing/requests/from-sales-order/{so_id}", headers=headers)
    assert request.status_code == 201, request.text
    request_id = int(request.json()["id"])

    approve = client.post(f"/api/purchasing/requests/{request_id}/approve", headers=headers)
    assert approve.status_code == 200, approve.text

    order = client.post(f"/api/purchasing/requests/{request_id}/convert-to-order", headers=headers)
    assert order.status_code == 201, order.text
    return order.json()


def test_purchasing_from_sales_order_approve_convert_receive_increases_stock(client, auth_headers):
    so_id = _create_large_sales_order(client, auth_headers)

    request_response = client.post(f"/api/purchasing/requests/from-sales-order/{so_id}", headers=auth_headers)
    assert request_response.status_code == 201, request_response.text
    request = request_response.json()
    assert request["request_no"].startswith("PR-")
    assert request["status"] == "pending_approval"
    assert request["lines"]
    assert all(float(line["shortage_quantity"]) > 0 for line in request["lines"])
    assert all(round(float(line["requested_quantity"]), 4) == round(float(line["shortage_quantity"]), 4) for line in request["lines"])

    approve_response = client.post(f"/api/purchasing/requests/{request['id']}/approve", headers=auth_headers)
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["status"] == "approved"

    order_response = client.post(f"/api/purchasing/requests/{request['id']}/convert-to-order", headers=auth_headers)
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    assert order["po_no"].startswith("PUR-")
    assert order["request_no"] == request["request_no"]
    assert order["status"] == "sent"
    assert order["lines"]

    cotton_line = next(line for line in order["lines"] if line["item_sku"] == "FAB-COT-001")
    before_qty = _stock_quantity(client, auth_headers, "FAB-COT-001")
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    supplier_id = _first_supplier_id(client, auth_headers)
    batch_no = f"{order['po_no']}-TEST"

    receive_response = client.post(
        f"/api/purchasing/orders/{order['id']}/receive",
        json={
            "supplier_id": supplier_id,
            "lines": [
                {
                    "purchase_order_line_id": cotton_line["id"],
                    "received_quantity": 5,
                    "batch_no": batch_no,
                    "warehouse_id": warehouse_id,
                    "cost_per_unit": 3.75,
                }
            ],
        },
        headers=auth_headers,
    )
    assert receive_response.status_code == 200, receive_response.text
    received_order = receive_response.json()
    assert received_order["status"] == "partially_received"
    received_line = next(line for line in received_order["lines"] if line["id"] == cotton_line["id"])
    assert float(received_line["received_quantity"]) == 5

    after_qty = _stock_quantity(client, auth_headers, "FAB-COT-001")
    assert round(after_qty - before_qty, 2) == 5.00

    from app.db.session import SessionLocal
    from app.models import StockBatch, StockMovement

    db = SessionLocal()
    try:
        batch = db.query(StockBatch).filter(StockBatch.batch_no == batch_no).first()
        assert batch is not None
        assert round(float(batch.quantity or 0), 2) == 5.00
        movement = (
            db.query(StockMovement)
            .filter(
                StockMovement.batch_id == batch.id,
                StockMovement.reference_type == "PurchaseOrderLine",
                StockMovement.reference_id == cotton_line["id"],
                StockMovement.movement_type == "receive",
            )
            .first()
        )
        assert movement is not None
        assert int(movement.to_warehouse_id) == warehouse_id
        assert round(float(movement.quantity or 0), 2) == 5.00
    finally:
        db.close()

    audit = client.get(f"/api/audit-logs?entity_type=PurchaseOrder&entity_id={order['id']}", headers=auth_headers)
    assert audit.status_code == 200, audit.text
    assert any(row["action"] == "update_status" for row in audit.json())


def test_purchasing_approve_requires_permission(client, auth_headers):
    so_id = _create_large_sales_order(client, auth_headers)
    request = client.post(f"/api/purchasing/requests/from-sales-order/{so_id}", headers=auth_headers)
    assert request.status_code == 201, request.text
    limited_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email="purchase.noapprove@example.com",
        permissions=["purchasing.view", "purchasing.receive"],
    )

    denied = client.post(f"/api/purchasing/requests/{request.json()['id']}/approve", headers=limited_headers)
    assert denied.status_code == 403, denied.text


def test_purchase_request_notifications_follow_approval_flow(client, auth_headers):
    manager_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email="purchase.manager.notify@example.com",
        permissions=["purchasing.view", "purchasing.approve"],
        department_code="ADM",
    )
    planning_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email="purchase.planning.notify@example.com",
        permissions=["purchasing.view", "purchasing.order"],
        department_code="PLN",
    )
    so_id = _create_large_sales_order(client, auth_headers)

    request = client.post(f"/api/purchasing/requests/from-sales-order/{so_id}", headers=auth_headers)
    assert request.status_code == 201, request.text
    request_no = request.json()["request_no"]

    manager_notes = client.get("/api/notifications?only_unread=true", headers=manager_headers)
    assert manager_notes.status_code == 200, manager_notes.text
    assert any(
        request_no in row["title"] and row["link"] == "/purchasing"
        for row in manager_notes.json()
    )

    approve = client.post(f"/api/purchasing/requests/{request.json()['id']}/approve", headers=manager_headers)
    assert approve.status_code == 200, approve.text

    planning_notes = client.get("/api/notifications?only_unread=true", headers=planning_headers)
    assert planning_notes.status_code == 200, planning_notes.text
    assert any(
        request_no in row["title"] and row["link"] == "/purchasing"
        for row in planning_notes.json()
    )


def test_purchasing_receive_requires_permission(client, auth_headers):
    order = _create_approved_purchase_order(client, auth_headers)
    cotton_line = next(line for line in order["lines"] if line["item_sku"] == "FAB-COT-001")
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    limited_headers = _create_user_with_permissions(
        client,
        auth_headers,
        email="purchase.noreceive@example.com",
        permissions=["purchasing.view"],
    )

    denied = client.post(
        f"/api/purchasing/orders/{order['id']}/receive",
        json={
            "lines": [
                {
                    "purchase_order_line_id": cotton_line["id"],
                    "received_quantity": 1,
                    "batch_no": f"{order['po_no']}-DENIED",
                    "warehouse_id": warehouse_id,
                }
            ],
        },
        headers=limited_headers,
    )
    assert denied.status_code == 403, denied.text


def test_draft_purchase_order_cannot_be_received(client, auth_headers):
    item = _item_by_sku(client, auth_headers, "FAB-COT-001")
    warehouse_id = _fabric_warehouse_id(client, auth_headers)
    supplier_id = _first_supplier_id(client, auth_headers)
    order = client.post(
        "/api/purchasing/orders",
        json={
            "supplier_id": supplier_id,
            "lines": [
                {
                    "item_id": item["id"],
                    "ordered_quantity": 3,
                    "unit": item["unit"],
                    "unit_cost": 4.25,
                    "warehouse_id": warehouse_id,
                }
            ],
        },
        headers=auth_headers,
    )
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["status"] == "draft"
    line = body["lines"][0]
    batch_no = f"{body['po_no']}-DRAFT-DENIED"

    denied = client.post(
        f"/api/purchasing/orders/{body['id']}/receive",
        json={
            "supplier_id": supplier_id,
            "lines": [
                {
                    "purchase_order_line_id": line["id"],
                    "received_quantity": 1,
                    "batch_no": batch_no,
                    "warehouse_id": warehouse_id,
                    "cost_per_unit": 4.25,
                }
            ],
        },
        headers=auth_headers,
    )
    assert denied.status_code == 409, denied.text

    from app.db.session import SessionLocal
    from app.models import StockBatch, StockMovement

    db = SessionLocal()
    try:
        assert db.query(StockBatch).filter(StockBatch.batch_no == batch_no).first() is None
        assert (
            db.query(StockMovement)
            .filter(
                StockMovement.reference_type == "PurchaseOrderLine",
                StockMovement.reference_id == line["id"],
                StockMovement.movement_type == "receive",
            )
            .count()
            == 0
        )
    finally:
        db.close()
