"""Integration tests for core production flow endpoints."""


def _prepare_sales_order_for_po(client, headers, sales_order_id: int) -> None:
    r = client.get(f"/api/sales-orders/{sales_order_id}", headers=headers)
    assert r.status_code == 200, r.text
    status = r.json()["status"]
    if status == "draft":
        r = client.post(f"/api/sales-orders/{sales_order_id}/confirm", headers=headers)
        assert r.status_code == 200, r.text
        status = r.json()["status"]
    if status == "confirmed":
        r = client.post(f"/api/planning/submit-estimate/{sales_order_id}", headers=headers)
        assert r.status_code == 200, r.text
        status = r.json()["status"]
    if status == "pending_sales_approval":
        r = client.post(f"/api/sales-orders/{sales_order_id}/approve-planning", headers=headers)
        assert r.status_code == 200, r.text
        status = r.json()["status"]
    assert status == "planning_approved"


def _create_client_sales_order(client, headers) -> int:
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "test order",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": 50, "unit_price": 12.5},
                {"model_id": 1, "color": "white", "size": "L", "quantity": 50, "unit_price": 12.5},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["id"]
    r = client.post(f"/api/sales-orders/{so_id}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    return so_id


def _planning_headers(client) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        data={"username": "planning@example.com", "password": "demo12345"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_full_flow(client, auth_headers):
    r = client.get("/api/sales-orders", headers=auth_headers)
    assert r.status_code == 200
    sales = r.json()
    assert len(sales) >= 1
    so_id = _create_client_sales_order(client, auth_headers)

    r = client.get(f"/api/planning/material-requirements/{so_id}", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1

    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 50},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()

    # Work orders are auto-created. This endpoint should remain idempotent.
    r = client.post(
        f"/api/production-orders/{po['id']}/create-work-orders?include_printing=false",
        headers=auth_headers,
    )
    assert r.status_code == 200

    r = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert r.status_code == 200
    wos = r.json()
    assert any(w["operation"] == "cutting" for w in wos)
    assert any(w["operation"] == "sewing" for w in wos)
    assert any(w["operation"] == "packaging" for w in wos)
    cutting_wo = next(w for w in wos if w["operation"] == "cutting")
    sewing_wo = next(w for w in wos if w["operation"] == "sewing")
    packaging_wo = next(w for w in wos if w["operation"] == "packaging")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 140.0,
            "input_unit": "meter",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 5.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 50, "count": 1},
                {"color": "white", "size": "L", "quantity": 50, "count": 1},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundles = r.json()["bundles"]
    assert len(bundles) == 2

    b1 = bundles[0]
    r = client.post(f"/api/bundles/{b1['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200
    r = client.post(f"/api/bundles/{b1['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "received_sewing"

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 100,
            "sewn_qty": 100,
            "passed_qty": 95,
            "failed_qty": 5,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "input_qty": 95,
            "packed_qty": 90,
            "damaged_qty": 5,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po["id"],
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": 30},
                {"model_id": 1, "color": "white", "size": "L", "quantity": 30},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert pkg["total_quantity"] == 60
    assert pkg["barcode"]

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "received_in_storage"


def test_sewing_record_updates_selected_line_assignment_progress(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_wo = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = r.json()[0]["id"]

    r = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow_id,
            "quantity": 40,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assignment_id = r.json()["id"]

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 25,
            "sewn_qty": 25,
            "passed_qty": 25,
            "failed_qty": 0,
            "sewing_assignment_id": assignment_id,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/assignments", headers=auth_headers)
    assert r.status_code == 200, r.text
    assignment = next(a for a in r.json() if a["id"] == assignment_id)
    assert assignment["completed_qty"] == 25
    assert assignment["status"] == "in_progress"

    # Over-completion is capped at planned assignment quantity.
    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 30,
            "sewn_qty": 30,
            "passed_qty": 30,
            "failed_qty": 0,
            "sewing_assignment_id": assignment_id,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/assignments", headers=auth_headers)
    assert r.status_code == 200, r.text
    assignment = next(a for a in r.json() if a["id"] == assignment_id)
    assert assignment["completed_qty"] == 40
    assert assignment["status"] == "completed"


def test_sewing_line_plan_consumes_brak_qty(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_wo = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = r.json()[0]["id"]

    r = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow_id,
            "quantity": 100,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assignment_id = r.json()["id"]

    # Scenario: input 100, output/passed 99, brak 1.
    # Brak piece should still consume line plan and not remain as "to sew".
    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 100,
            "sewn_qty": 99,
            "passed_qty": 99,
            "failed_qty": 1,
            "rejected_qty": 0,
            "sewing_assignment_id": assignment_id,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/assignments", headers=auth_headers)
    assert r.status_code == 200, r.text
    assignment = next(a for a in r.json() if a["id"] == assignment_id)
    assert assignment["completed_qty"] == 100
    assert assignment["status"] == "completed"


def test_package_over_capacity_blocked_without_admin_override(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201
    po_id = r.json()["id"]

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 70}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_package_bulk_create(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 200,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 200}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.post(
        "/api/packages/bulk",
        json={
            "count": 3,
            "production_order_id": po_id,
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 50}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert len(body["package_ids"]) == 3


def test_branded_production_requires_approved_model(client, auth_headers):
    r = client.post(
        "/api/models",
        json={"code": "DRAFT-001", "name": "Draft model", "status": "draft"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    mid = r.json()["id"]
    r = client.post(
        "/api/planning/create-branded-production",
        json={"production_type": "branded_stock", "model_id": mid, "planned_quantity": 10, "items": []},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_planning_assign_rejects_overloaded_sewing_line(client, auth_headers):
    planning_headers = _planning_headers(client)
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 120,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 120}],
        },
        headers=planning_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=planning_headers)
    assert r.status_code == 200, r.text
    sewing_wo = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.get("/api/sewing-flows", headers=planning_headers)
    assert r.status_code == 200, r.text
    flow_id = r.json()[0]["id"]

    r = client.patch(
        f"/api/sewing-flows/{flow_id}",
        json={"capacity_per_day": 10},
        headers=planning_headers,
    )
    assert r.status_code == 200, r.text

    # 120 pcs remaining against a line capacity of 10/day must be blocked.
    r = client.patch(
        f"/api/work-orders/{sewing_wo['id']}",
        json={"sewing_flow_id": flow_id},
        headers=planning_headers,
    )
    assert r.status_code == 409, r.text
