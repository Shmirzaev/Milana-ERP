"""Integration tests for core production flow endpoints."""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


def _prepare_sales_order_for_po(client, headers, sales_order_id: int) -> None:
    r = client.get(f"/api/sales-orders/{sales_order_id}", headers=headers)
    assert r.status_code == 200, r.text
    status = r.json()["status"]
    if status == "draft":
        r = client.post(f"/api/sales-orders/{sales_order_id}/confirm", headers=headers)
        assert r.status_code == 200, r.text
        status = r.json()["status"]
    assert status == "confirmed"


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
    r = None
    for password in ("demo12345", "PlanningResetPassword123!"):
        r = client.post(
            "/api/auth/token",
            data={"username": "planning@example.com", "password": password},
        )
        if r.status_code == 200:
            break
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_package_for_change_request(client, headers, quantity: int = 20) -> int:
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 60,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": quantity},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _create_bundle_for_scan(client, headers) -> dict:
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 50,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.post(
        "/api/bundles",
        json={
            "production_order_id": po_id,
            "model_id": 1,
            "color": "white",
            "size": "M",
            "quantity": 50,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_client_production_uses_sales_order_reference(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    r = client.get(f"/api/sales-orders/{so_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    so_no = r.json()["order_no"]

    payload = {
        "production_type": "client_order",
        "sales_order_id": so_id,
        "model_id": 1,
        "planned_quantity": 50,
        "items": [
            {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
        ],
    }
    r = client.post("/api/planning/create-production-order", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["production_no"] == so_no
    assert first["order_no"] == so_no
    assert first["sales_order_no"] == so_no

    r = client.get(f"/api/work-orders?production_order_id={first['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()
    assert all(row["order_no"] == so_no for row in r.json())

    r = client.post("/api/production-orders", json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    second = r.json()
    assert second["production_no"] == f"{so_no}-2"
    assert second["order_no"] == so_no
    assert second["sales_order_no"] == so_no


def test_standalone_production_order_reference_uses_so_format(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 60,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["production_no"].startswith("PO-")
    assert po["order_no"].startswith("SO-")
    assert po["order_no"] == po["production_no"].replace("PO-", "SO-", 1)

    r = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    wos = r.json()
    assert wos
    assert all(row["order_no"] == po["order_no"] for row in wos)


def test_package_barcode_lookup_accepts_label_qr_payload(client, auth_headers):
    pkg_id = _create_package_for_change_request(client, auth_headers, quantity=20)

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    pkg = r.json()
    qr_payload = f"PACKAGE:{pkg['package_no']}|{pkg['barcode']}"

    r = client.get(f"/api/packages/barcode/{quote(qr_payload, safe='')}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["id"]) == pkg_id


def test_bundle_barcode_lookup_accepts_label_qr_payload(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    qr_payload = f"BUNDLE:{bundle['bundle_no']}|{bundle['barcode']}"

    r = client.get(f"/api/bundles/lookup?code={quote(qr_payload, safe='')}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["id"]) == int(bundle["id"])

    r = client.get(f"/api/bundles/barcode/{quote(qr_payload, safe='')}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["id"]) == int(bundle["id"])


def test_bundle_duplicate_receive_scan_is_rejected(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)

    r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/work-orders?production_order_id={bundle['production_order_id']}&operation=sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_wo = r.json()[0]
    assert int(sewing_wo["actual_input_qty"]) == int(bundle["quantity"])
    assert int(sewing_wo["received_bundle_count"]) == 1
    assert int(sewing_wo["received_bundle_qty"]) == int(bundle["quantity"])

    r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "already received at sewing" in r.text


def test_package_edit_request_applies_after_management_approval(client, auth_headers):
    pkg_id = _create_package_for_change_request(client, auth_headers, quantity=20)

    r = client.post(
        f"/api/packages/{pkg_id}/change-requests",
        json={
            "request_type": "edit",
            "reason": "quantity correction",
            "payload": {
                "color": "white",
                "package_type": "box",
                "capacity": 60,
                "items": [
                    {"model_id": 1, "color": "white", "size": "M", "quantity": 12},
                    {"model_id": 1, "color": "white", "size": "L", "quantity": 18},
                ],
            },
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    req_id = int(r.json()["id"])
    assert r.json()["status"] == "pending"

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["total_quantity"]) == 20
    assert r.json()["package_type"] == "bag"

    r = client.post(f"/api/packages/change-requests/{req_id}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert int(detail["total_quantity"]) == 30
    assert detail["package_type"] == "box"
    assert sorted((row["size"], int(row["quantity"])) for row in detail["items"]) == [("L", 18), ("M", 12)]

    from app.db.session import SessionLocal
    from app.models import FinishedGoodsStock

    db = SessionLocal()
    try:
        rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg_id).all()
        assert sum(int(row.quantity or 0) for row in rows) == 30
        assert sorted((row.size, int(row.available_qty or 0)) for row in rows) == [("L", 18), ("M", 12)]
    finally:
        db.close()


def test_package_delete_request_removes_package_after_management_approval(client, auth_headers):
    pkg_id = _create_package_for_change_request(client, auth_headers, quantity=15)

    r = client.post(
        f"/api/packages/{pkg_id}/change-requests",
        json={"request_type": "delete", "reason": "duplicate package"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    req_id = int(r.json()["id"])

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.post(f"/api/packages/change-requests/{req_id}/approve", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 404, r.text

    from app.db.session import SessionLocal
    from app.models import FinishedGoodsStock

    db = SessionLocal()
    try:
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == pkg_id).count() == 0
    finally:
        db.close()


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
            "estimated_material_code": "FAB-COT-001",
            "estimated_material_amount": 140.0,
            "estimated_material_unit": "kg",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 50},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()
    assert po["estimated_material_code"] == "FAB-COT-001"
    assert float(po["estimated_material_amount"]) == 140.0
    assert po["estimated_material_unit"] == "kg"

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
            "input_unit": "kg",
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

    r = client.get(f"/api/production-orders/{po['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po_detail = r.json()
    assert int(po_detail["planned_quantity"]) == 100
    assert int(po_detail["actual_bundle_quantity"]) == 100
    assert int(po_detail["actual_bundle_count"]) == 2

    b1 = bundles[0]
    b2 = bundles[1]
    r = client.post(f"/api/bundles/{b2['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_sewing"

    r = client.get(f"/api/work-orders/{sewing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["actual_input_qty"]) == 50
    assert int(r.json()["received_bundle_count"]) == 1
    assert int(r.json()["received_bundle_qty"]) == 50

    r = client.post(f"/api/bundles/{b1['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200
    r = client.post(f"/api/bundles/{b1['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "received_sewing"

    r = client.get(f"/api/work-orders/{sewing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["actual_input_qty"]) == 100
    assert int(r.json()["received_bundle_count"]) == 2
    assert int(r.json()["received_bundle_qty"]) == 100

    r = client.get("/api/inbox?dept=PKG", headers=auth_headers)
    assert r.status_code == 200, r.text
    pkg_expected = [
        row for row in r.json()["incoming_work_orders"]
        if int(row["production_order_id"]) == int(po["id"])
    ]
    assert pkg_expected
    assert pkg_expected[0]["source_operation"] == "sewing"
    assert pkg_expected[0]["target_operation"] == "packaging"
    assert int(pkg_expected[0]["ready_qty"]) == 0
    assert int(pkg_expected[0]["expected_qty"]) == 100

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 0,
            "sewn_qty": 100,
            "passed_qty": 95,
            "failed_qty": 5,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get("/api/inbox?dept=PKG", headers=auth_headers)
    assert r.status_code == 200, r.text
    pkg_incoming = [
        row for row in r.json()["incoming_work_orders"]
        if int(row["production_order_id"]) == int(po["id"])
    ]
    assert pkg_incoming
    assert pkg_incoming[0]["source_operation"] == "sewing"
    assert pkg_incoming[0]["target_operation"] == "packaging"
    assert int(pkg_incoming[0]["ready_qty"]) == 95
    assert int(pkg_incoming[0]["expected_qty"]) == 100

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


def test_cutting_routes_bundles_to_selected_sewing_factories(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
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
    po_id = r.json()["id"]

    r = client.get("/api/departments", headers=auth_headers)
    assert r.status_code == 200, r.text
    dept_by_code = {d["code"]: d for d in r.json()}
    assert "MIL" in dept_by_code
    assert "BST" in dept_by_code

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 140.0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 5.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 50, "count": 1, "next": "sewing", "sewing_factory": "milana"},
                {"color": "white", "size": "L", "quantity": 50, "count": 1, "next": "sewing", "sewing_factory": "besttex"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    milana_bundle, besttex_bundle = r.json()["bundles"]
    assert milana_bundle["sewing_factory_code"] == "MIL"
    assert besttex_bundle["sewing_factory_code"] == "BST"

    r = client.get(f"/api/bundles/{milana_bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["next_department_id"] == dept_by_code["MIL"]["id"]

    r = client.get(f"/api/bundles/{besttex_bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["next_department_id"] == dept_by_code["BST"]["id"]

    r = client.get("/api/inbox?dept=MIL", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(b["id"] == milana_bundle["id"] for b in r.json()["incoming_bundles"])

    r = client.get("/api/inbox?dept=BST", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(b["id"] == besttex_bundle["id"] for b in r.json()["incoming_bundles"])

    r = client.post(f"/api/bundles/{besttex_bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_sewing"
    assert r.json()["current_department_id"] == dept_by_code["BST"]["id"]

    r = client.post(f"/api/bundles/{milana_bundle['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_to_sewing"
    assert r.json()["next_department_id"] == dept_by_code["MIL"]["id"]
    assert r.json()["current_department_id"] == dept_by_code["MIL"]["id"]


def test_printed_bundle_keeps_cutting_selected_sewing_factory(client, auth_headers):
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "items": [
                {
                    "model_id": 1,
                    "color": "white",
                    "size": "M",
                    "quantity": 100,
                    "unit_price": 12.5,
                    "printing_required": True,
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["id"]
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

    r = client.get("/api/departments", headers=auth_headers)
    assert r.status_code == 200, r.text
    dept_by_code = {d["code"]: d for d in r.json()}

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 140.0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 5.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 1, "next": "printing", "sewing_factory": "besttex"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundle = r.json()["bundles"][0]
    assert bundle["sewing_factory_code"] == "BST"

    r = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["next_department_id"] == dept_by_code["PRT"]["id"]

    r = client.post(f"/api/bundles/{bundle['id']}/send-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/bundles/{bundle['id']}/receive-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/bundles/{bundle['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sent_to_sewing"
    assert body["sewing_factory_code"] == "BST"
    assert body["next_department_id"] == dept_by_code["BST"]["id"]
    assert body["current_department_id"] == dept_by_code["BST"]["id"]


def test_cutting_overproduction_keeps_downstream_stage_plan(client, auth_headers):
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
    by_op = {w["operation"]: w for w in r.json()}
    cutting_wo = by_op["cutting"]
    sewing_wo = by_op["sewing"]
    packaging_wo = by_op["packaging"]
    storage_wo = by_op["storage_transfer"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 145.0,
            "input_unit": "kg",
            "cut_pieces": 108,
            "passed_pieces": 108,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["planned_quantity"]) == 100
    assert int(po["actual_cut_quantity"]) == 108
    refreshed = {w["operation"]: w for w in po["work_orders"]}
    assert int(refreshed["cutting"]["actual_output_qty"]) == 108
    assert int(refreshed["cutting"]["planned_output_qty"]) == 100
    for op in ("sewing", "packaging", "storage_transfer"):
        assert int(refreshed[op]["planned_input_qty"]) == 100
        assert int(refreshed[op]["planned_output_qty"]) == 100

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 108,
            "sewn_qty": 108,
            "passed_qty": 108,
            "failed_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "input_qty": 108,
            "packed_qty": 108,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{storage_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["planned_output_qty"]) == 100


def test_cutting_overproduction_keeps_batch_and_order_plan(client, auth_headers):
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
            "batches": [
                {"name": "A", "planned_quantity": 60},
                {"name": "B", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_a = next(b for b in po["batches"] if b["name"] == "A")
    by_op = {w["operation"]: w for w in po["work_orders"]}
    cut_wo = by_op["cutting"]
    sew_wo = by_op["sewing"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cut_wo["id"],
            "production_batch_id": batch_a["id"],
            "fabric_batch_id": None,
            "input_quantity": 90.0,
            "input_unit": "kg",
            "cut_pieces": 65,
            "passed_pieces": 65,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["planned_quantity"]) == 100
    assert int(po["actual_cut_quantity"]) == 65
    batch_a = next(b for b in po["batches"] if b["name"] == "A")
    batch_b = next(b for b in po["batches"] if b["name"] == "B")
    assert int(batch_a["planned_quantity"]) == 60
    assert int(batch_b["planned_quantity"]) == 40
    refreshed = {w["operation"]: w for w in po["work_orders"]}
    assert int(refreshed["sewing"]["planned_input_qty"]) == 100
    assert int(refreshed["sewing"]["planned_output_qty"]) == 100

    r = client.get(f"/api/work-orders/{sew_wo['id']}/sewing-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress_a = next(row for row in r.json()["items"] if row["id"] == batch_a["id"])
    assert int(progress_a["planned_quantity"]) == 60


def test_production_order_planning_fields_lock_after_cutting_starts(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
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
    po_id = r.json()["id"]

    r = client.patch(
        f"/api/production-orders/{po_id}",
        json={
            "estimated_material_code": "FAB-EDIT-001",
            "estimated_material_amount": 155.5,
            "estimated_material_unit": "kg",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["estimated_material_code"] == "FAB-EDIT-001"

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(f"/api/work-orders/{cutting_wo['id']}/start", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"

    r = client.patch(
        f"/api/production-orders/{po_id}",
        json={"estimated_material_code": "FAB-TOO-LATE"},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_planning_can_create_batched_production_and_track_batches(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
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
            "batches": [
                {"name": "Batch 1", "planned_quantity": 60},
                {"name": "Batch 2", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    wos = r.json()
    assert len(wos) == 4
    assert {w["operation"] for w in wos} == {"cutting", "sewing", "packaging", "storage_transfer"}
    assert all(w["production_batch_id"] is None for w in wos)
    assert all(int(w["planned_output_qty"]) == 100 for w in wos)

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next((p for p in r.json() if p["production_order_id"] == po_id), None)
    assert proc is not None
    assert len(proc["batches"]) == 2
    assert sorted(int(b["planned_quantity"]) for b in proc["batches"]) == [40, 60]
    assert all(str(b.get("batch_no", "")).startswith("BT-") for b in proc["batches"])


def test_process_tracking_internal_batch_progress_uses_batch_planned_quantity(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
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
            "batches": [
                {"name": "Batch A", "planned_quantity": 60},
                {"name": "Batch B", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_a = next(b for b in po["batches"] if b["name"] == "Batch A")
    batch_b = next(b for b in po["batches"] if b["name"] == "Batch B")
    cutting_wo = next(w for w in po["work_orders"] if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch_a["id"],
            "fabric_batch_id": None,
            "input_quantity": 10,
            "input_unit": "kg",
            "cut_pieces": 60,
            "passed_pieces": 60,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json() if p["production_order_id"] == po_id)
    total_cutting = next(s for s in proc["stages"] if s["operation"] == "cutting")
    assert int(total_cutting["planned"]) == 100
    assert int(total_cutting["completed"]) == 60
    assert float(total_cutting["progress_pct"]) == 60.0

    batch_a_proc = next(b for b in proc["batches"] if b["id"] == batch_a["id"])
    batch_a_cutting = next(s for s in batch_a_proc["stages"] if s["operation"] == "cutting")
    assert int(batch_a_cutting["planned"]) == 60
    assert int(batch_a_cutting["completed"]) == 60
    assert float(batch_a_cutting["progress_pct"]) == 100.0
    assert batch_a_cutting["status"] == "completed"

    batch_b_proc = next(b for b in proc["batches"] if b["id"] == batch_b["id"])
    batch_b_cutting = next(s for s in batch_b_proc["stages"] if s["operation"] == "cutting")
    assert int(batch_b_cutting["planned"]) == 40
    assert int(batch_b_cutting["completed"]) == 0
    assert float(batch_b_cutting["progress_pct"]) == 0.0
    assert batch_b_cutting["status"] == "waiting"


def test_process_tracking_internal_batch_storage_uses_received_packages(client, auth_headers):
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
            "batches": [
                {"name": "Batch A", "planned_quantity": 60},
                {"name": "Batch B", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_a = next(b for b in po["batches"] if b["name"] == "Batch A")
    batch_b = next(b for b in po["batches"] if b["name"] == "Batch B")

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "production_batch_id": batch_a["id"],
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert pkg["production_batch_id"] == batch_a["id"]

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_in_storage"

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json() if p["production_order_id"] == po_id)
    batch_a_proc = next(b for b in proc["batches"] if b["id"] == batch_a["id"])
    batch_a_storage = next(s for s in batch_a_proc["stages"] if s["operation"] == "storage_transfer")
    assert int(batch_a_storage["planned"]) == 60
    assert int(batch_a_storage["completed"]) == 60
    assert float(batch_a_storage["progress_pct"]) == 100.0
    assert batch_a_storage["status"] == "completed"

    batch_b_proc = next(b for b in proc["batches"] if b["id"] == batch_b["id"])
    batch_b_storage = next(s for s in batch_b_proc["stages"] if s["operation"] == "storage_transfer")
    assert int(batch_b_storage["completed"]) == 0
    assert batch_b_storage["status"] == "waiting"


def test_package_can_merge_leftovers_from_multiple_batches(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60}],
            "batches": [
                {"name": "Batch A", "planned_quantity": 50},
                {"name": "Batch B", "planned_quantity": 10},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_a = next(b for b in po["batches"] if b["name"] == "Batch A")
    batch_b = next(b for b in po["batches"] if b["name"] == "Batch B")

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 60}],
            "batch_allocations": [
                {"production_batch_id": batch_a["id"], "quantity": 50},
                {"production_batch_id": batch_b["id"], "quantity": 10},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert pkg["production_batch_id"] is None

    detail = client.get(f"/api/packages/{pkg['id']}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    allocations = sorted(detail.json()["batch_allocations"], key=lambda x: x["production_batch_id"])
    assert [a["quantity"] for a in allocations] == [50, 10]

    label = client.get(f"/api/packages/{pkg['id']}/label", headers=auth_headers)
    assert label.status_code == 200, label.text
    assert "Batch A" in label.text
    assert "Batch B" in label.text

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json() if p["production_order_id"] == po_id)
    batch_a_proc = next(b for b in proc["batches"] if b["id"] == batch_a["id"])
    batch_b_proc = next(b for b in proc["batches"] if b["id"] == batch_b["id"])
    batch_a_storage = next(s for s in batch_a_proc["stages"] if s["operation"] == "storage_transfer")
    batch_b_storage = next(s for s in batch_b_proc["stages"] if s["operation"] == "storage_transfer")
    assert int(batch_a_storage["completed"]) == 50
    assert int(batch_b_storage["completed"]) == 10


def test_cutting_can_split_existing_unsplit_order_into_batches(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 1200,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 1200},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    old_cutting = next(w for w in r.json() if w["operation"] == "cutting")
    old_cutting_id = old_cutting["id"]

    r = client.post(
        f"/api/work-orders/{old_cutting_id}/split-batches",
        json={
            "batches": [
                {"name": "Batch A", "planned_quantity": 400},
                {"name": "Batch B", "planned_quantity": 400},
                {"name": "Batch C", "planned_quantity": 400},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert int(body["work_order_id"]) == old_cutting_id
    assert body["kept_single_work_order"] is True

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert len(po["batches"]) == 3
    assert sorted(int(b["planned_quantity"]) for b in po["batches"]) == [400, 400, 400]
    assert all(str(b.get("batch_no", "")).startswith("BT-") for b in po["batches"])
    assert len(po["work_orders"]) == 4
    assert any(w["id"] == old_cutting_id and w["operation"] == "cutting" for w in po["work_orders"])
    cutting_wos = [w for w in po["work_orders"] if w["operation"] == "cutting"]
    assert len(cutting_wos) == 1
    assert int(cutting_wos[0]["planned_output_qty"]) == 1200
    assert cutting_wos[0]["production_batch_id"] is None

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next((p for p in r.json() if p["production_order_id"] == po_id), None)
    assert proc is not None
    assert len(proc["batches"]) == 3

    batch_a = next(b for b in po["batches"] if b["name"] == "Batch A")
    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": old_cutting_id,
            "production_batch_id": batch_a["id"],
            "fabric_batch_id": None,
            "input_quantity": 10,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{old_cutting_id}/cutting-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress = r.json()["items"]
    first = next(row for row in progress if row["id"] == batch_a["id"])
    assert int(first["passed_pieces"]) == 100


def test_cutting_split_batches_can_exceed_plan_and_report_actual_quantity(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 900,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 900},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(
        f"/api/work-orders/{cutting_wo['id']}/split-batches",
        json={"batches": [{"name": "Batch 1", "planned_quantity": 1500}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["planned_quantity"]) == 900
    assert int(po["actual_quantity"]) == 1500
    assert len(po["batches"]) == 1
    assert int(po["batches"][0]["planned_quantity"]) == 1500
    refreshed_cutting = next(w for w in po["work_orders"] if w["operation"] == "cutting")
    assert int(refreshed_cutting["planned_output_qty"]) == 900

    r = client.get(f"/api/work-orders/{cutting_wo['id']}/cutting-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress = r.json()["items"][0]
    assert int(progress["planned_quantity"]) == 1500
    assert int(progress["remaining_quantity"]) == 1500


def test_sewing_batch_failed_quantity_counts_as_processed_for_remaining(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
            ],
            "batches": [
                {"name": "Batch 1", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch = po["batches"][0]
    by_op = {w["operation"]: w for w in po["work_orders"]}
    cutting_wo = by_op["cutting"]
    sewing_wo = by_op["sewing"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 100.0,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 600,
            "sewn_qty": 599,
            "passed_qty": 599,
            "failed_qty": 1,
            "rework_qty": 0,
            "rejected_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/sewing-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress = r.json()["items"][0]
    assert int(progress["passed_qty"]) == 599
    assert int(progress["failed_qty"]) == 1
    assert int(progress["remaining_quantity"]) == 0
    assert float(progress["progress_pct"]) == 100.0


def test_packaging_progress_counts_upstream_failed_as_resolved(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
            ],
            "batches": [
                {"name": "Batch 1", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch = po["batches"][0]
    by_op = {w["operation"]: w for w in po["work_orders"]}
    cutting_wo = by_op["cutting"]
    sewing_wo = by_op["sewing"]
    packaging_wo = by_op["packaging"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 100.0,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 600,
            "sewn_qty": 599,
            "passed_qty": 599,
            "failed_qty": 1,
            "rework_qty": 0,
            "rejected_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 599,
            "packed_qty": 599,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{packaging_wo['id']}/packaging-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress = r.json()["items"][0]
    assert int(progress["packed_qty"]) == 599
    assert int(progress["damaged_qty"]) == 0
    assert int(progress["remaining_quantity"]) == 0
    assert float(progress["progress_pct"]) == 100.0
    assert int(progress["available_to_package"]) == 599


def test_actual_quantity_mismatch_allows_breakdown_correction(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 900,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 450},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 450},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(
        f"/api/work-orders/{cutting_wo['id']}/split-batches",
        json={"batches": [{"name": "Batch 1", "planned_quantity": 1500}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    item_m = next(i for i in po["items"] if i["size"] == "M")
    item_l = next(i for i in po["items"] if i["size"] == "L")

    r = client.put(
        f"/api/production-orders/{po_id}/breakdown",
        json={
            "items": [
                {"id": item_m["id"], "color": "white", "size": "M", "planned_quantity": 800},
                {"id": item_l["id"], "color": "white", "size": "L", "planned_quantity": 700},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["planned_quantity"]) == 900
    assert int(po["actual_quantity"]) == 1500
    assert sorted((i["size"], int(i["planned_quantity"])) for i in po["items"]) == [("L", 700), ("M", 800)]

    r = client.put(
        f"/api/production-orders/{po_id}/breakdown",
        json={
            "items": [
                {"id": item_m["id"], "color": "white", "size": "M", "planned_quantity": 500},
                {"id": item_l["id"], "color": "white", "size": "L", "planned_quantity": 500},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "actual quantity" in r.text


def test_internal_batches_flow_separately_across_printing_sewing_packaging(client, auth_headers):
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "batched stages",
            "items": [
                {
                    "model_id": 1,
                    "color": "white",
                    "size": "M",
                    "quantity": 100,
                    "unit_price": 12.5,
                    "printing_required": True,
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["id"]
    r = client.post(f"/api/sales-orders/{so_id}/confirm", headers=auth_headers)
    assert r.status_code == 200, r.text
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
            "batches": [
                {"name": "A", "planned_quantity": 60},
                {"name": "B", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_a = next(b for b in po["batches"] if b["name"] == "A")
    batch_b = next(b for b in po["batches"] if b["name"] == "B")
    by_op = {w["operation"]: w for w in po["work_orders"]}
    cut_wo = by_op["cutting"]
    prt_wo = by_op["printing"]
    sew_wo = by_op["sewing"]
    pkg_wo = by_op["packaging"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cut_wo["id"],
            "production_batch_id": batch_a["id"],
            "fabric_batch_id": None,
            "input_quantity": 80.0,
            "input_unit": "kg",
            "cut_pieces": 60,
            "passed_pieces": 60,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cut_wo["id"],
            "production_batch_id": batch_b["id"],
            "fabric_batch_id": None,
            "input_quantity": 55.0,
            "input_unit": "kg",
            "cut_pieces": 40,
            "passed_pieces": 40,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        f"/api/work-orders/{prt_wo['id']}/collect",
        json={"deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/printing/records",
        json={
            "work_order_id": prt_wo["id"],
            "input_qty": 60,
            "printed_qty": 60,
            "passed_qty": 58,
            "rejected_qty": 2,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text

    r = client.post(
        "/api/printing/records",
        json={
            "work_order_id": prt_wo["id"],
            "production_batch_id": batch_a["id"],
            "input_qty": 60,
            "printed_qty": 60,
            "passed_qty": 58,
            "rejected_qty": 2,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sew_wo["id"],
            "production_batch_id": batch_a["id"],
            "input_qty": 59,
            "sewn_qty": 59,
            "passed_qty": 59,
            "failed_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sew_wo["id"],
            "production_batch_id": batch_a["id"],
            "input_qty": 58,
            "sewn_qty": 58,
            "passed_qty": 58,
            "failed_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": pkg_wo["id"],
            "production_batch_id": batch_a["id"],
            "input_qty": 59,
            "packed_qty": 59,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": pkg_wo["id"],
            "production_batch_id": batch_a["id"],
            "input_qty": 58,
            "packed_qty": 57,
            "damaged_qty": 1,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{prt_wo['id']}/printing-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    prt_progress = r.json()["items"]
    prt_a = next(x for x in prt_progress if x["id"] == batch_a["id"])
    prt_b = next(x for x in prt_progress if x["id"] == batch_b["id"])
    assert int(prt_a["passed_qty"]) == 58
    assert int(prt_b["passed_qty"]) == 0

    r = client.get(f"/api/work-orders/{sew_wo['id']}/sewing-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    sew_progress = r.json()["items"]
    sew_a = next(x for x in sew_progress if x["id"] == batch_a["id"])
    sew_b = next(x for x in sew_progress if x["id"] == batch_b["id"])
    assert int(sew_a["passed_qty"]) == 58
    assert int(sew_b["passed_qty"]) == 0

    r = client.get(f"/api/work-orders/{pkg_wo['id']}/packaging-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    pkg_progress = r.json()["items"]
    pkg_a = next(x for x in pkg_progress if x["id"] == batch_a["id"])
    pkg_b = next(x for x in pkg_progress if x["id"] == batch_b["id"])
    assert int(pkg_a["packed_qty"]) == 57
    assert int(pkg_b["packed_qty"]) == 0


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

    r = client.post(
        "/api/sewing-flows",
        json={
            "name": f"Test Line {po_id}",
            "code": f"TST-{po_id}",
            "capacity_per_day": 200,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]

    start = datetime.now(timezone.utc) - timedelta(hours=1)
    end = datetime.now(timezone.utc) + timedelta(hours=23)

    r = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow_id,
            "quantity": 100,
            "planned_start": start.isoformat(),
            "planned_end": end.isoformat(),
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

    # Completed assignment should immediately free the line.
    r = client.get(f"/api/sewing-flows/{flow_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow = r.json()
    assert flow["active_work_orders"] == 0
    assert flow["planned_units"] == 0

    r = client.get(f"/api/sewing-flows/{flow_id}/utilization", headers=auth_headers)
    assert r.status_code == 200, r.text
    util = r.json()
    assert util["committed_today"] == 0


def test_list_unassigned_sewing_work_orders_filter(client, auth_headers):
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

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&unassigned_flow=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    unassigned_before = [w["id"] for w in r.json()]
    assert sewing_wo["id"] in unassigned_before

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = r.json()[0]["id"]

    r = client.patch(
        f"/api/work-orders/{sewing_wo['id']}",
        json={"sewing_flow_id": flow_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&unassigned_flow=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    unassigned_after = [w["id"] for w in r.json()]
    assert sewing_wo["id"] not in unassigned_after


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


def test_package_bulk_create_accepts_per_package_weights(client, auth_headers):
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
            "weight_kg_values": [11.1, 11.25, 11.4],
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 50}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    ids = r.json()["package_ids"]
    assert len(ids) == 3

    weights = []
    for pid in ids:
        detail = client.get(f"/api/packages/{pid}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        weights.append(float(detail.json()["weight_kg"]))
    assert weights == [11.1, 11.25, 11.4]


def test_package_list_backfills_saved_qr_codes(client, auth_headers):
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
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.post(
        "/api/packages/bulk",
        json={
            "count": 2,
            "production_order_id": po_id,
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    ids = {int(pid) for pid in r.json()["package_ids"]}

    from app.db.session import SessionLocal
    from app.models import Package

    db = SessionLocal()
    try:
        for pkg in db.query(Package).filter(Package.id.in_(ids)).all():
            pkg.qr_code_url = None
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/packages?production_order_id={po_id}&include_total=true&page=1&page_size=500", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = [row for row in r.json()["rows"] if int(row["id"]) in ids]
    assert len(rows) == 2
    assert all(str(row["qr_code_url"]).startswith("/storage/barcodes/") for row in rows)

    db = SessionLocal()
    try:
        persisted = db.query(Package).filter(Package.id.in_(ids)).all()
        assert all(pkg.qr_code_url for pkg in persisted)
    finally:
        db.close()


def test_storage_transfer_work_order_completes_after_full_storage_intake(client, auth_headers):
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": 60, "unit_price": 12.5},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["id"]
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_op = {w["operation"]: w for w in r.json()}
    stg_wo = by_op["storage_transfer"]

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_in_storage"

    r = client.get(f"/api/work-orders/{stg_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    refreshed = r.json()
    assert int(refreshed["passed_qty"]) == 60
    assert refreshed["status"] == "completed"


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


def test_assignment_capacity_ignores_completed_work_orders(client, auth_headers):
    so_1 = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_1)
    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_1,
            "model_id": 1,
            "planned_quantity": 200,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 200}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_1 = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_1}", headers=auth_headers)
    assert r.status_code == 200, r.text
    sew_1 = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.post(
        "/api/sewing-flows",
        json={
            "name": f"Cap Test {po_1}",
            "code": f"CAP-{po_1}",
            "capacity_per_day": 200,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    flow_id = r.json()["id"]

    start = datetime.now(timezone.utc) - timedelta(hours=1)
    end = datetime.now(timezone.utc) + timedelta(hours=23)
    r = client.post(
        f"/api/work-orders/{sew_1['id']}/assignments",
        json={
            "work_order_id": sew_1["id"],
            "sewing_flow_id": flow_id,
            "quantity": 200,
            "planned_start": start.isoformat(),
            "planned_end": end.isoformat(),
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(f"/api/work-orders/{sew_1['id']}/complete", headers=auth_headers)
    assert r.status_code == 200, r.text

    so_2 = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_2)
    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_2,
            "model_id": 1,
            "planned_quantity": 200,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 200}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_2 = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_2}", headers=auth_headers)
    assert r.status_code == 200, r.text
    sew_2 = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.post(
        f"/api/work-orders/{sew_2['id']}/assignments",
        json={
            "work_order_id": sew_2["id"],
            "sewing_flow_id": flow_id,
            "quantity": 200,
            "planned_start": start.isoformat(),
            "planned_end": end.isoformat(),
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text


def test_printing_work_starts_pending_until_collected(client, auth_headers):
    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "client_order",
            "notes": "printing queue test",
            "items": [
                {
                    "model_id": 1,
                    "color": "white",
                    "size": "M",
                    "quantity": 100,
                    "unit_price": 12.5,
                    "printing_required": True,
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so_id = r.json()["id"]
    r = client.post(f"/api/sales-orders/{so_id}/confirm", headers=auth_headers)
    assert r.status_code == 200, r.text
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
    by_op = {w["operation"]: w for w in r.json()}
    cutting_wo = by_op["cutting"]
    printing_wo = by_op["printing"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 2.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 1, "next": "printing"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundle_id = r.json()["bundles"][0]["id"]

    r = client.get(f"/api/work-orders/{printing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    r = client.post(f"/api/bundles/{bundle_id}/send-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/bundles/{bundle_id}/receive-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/work-orders/{printing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"

    r = client.post(
        "/api/printing/records",
        json={
            "work_order_id": printing_wo["id"],
            "input_qty": 10,
            "printed_qty": 10,
            "passed_qty": 10,
            "rejected_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text

    r = client.post(
        f"/api/work-orders/{printing_wo['id']}/collect",
        json={
            "deadline": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "notes": "Master accepted queue",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected"
    assert r.json()["deadline"] is not None

    r = client.post(
        "/api/printing/records",
        json={
            "work_order_id": printing_wo["id"],
            "input_qty": 10,
            "printed_qty": 10,
            "passed_qty": 10,
            "rejected_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{printing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"
    assert r.json()["start_time"] is not None
