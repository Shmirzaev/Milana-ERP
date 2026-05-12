"""Integration test for the main production flow.

1. Get a sales order and its material requirements
2. Create a production order
3. Generate work orders
4. Post a cutting record that creates bundles
5. Scan-transition a bundle through to sewing
6. Pack a finished package
7. Receive the package in finished-goods storage
"""


def test_full_flow(client, auth_headers):
    # 1) Sales orders exist from seed
    r = client.get("/api/sales-orders", headers=auth_headers)
    assert r.status_code == 200
    sales = r.json()
    assert len(sales) >= 1
    so = sales[0]

    # Material requirements
    r = client.get(f"/api/planning/material-requirements/{so['id']}", headers=auth_headers)
    assert r.status_code == 200
    mr = r.json()
    assert len(mr) >= 1

    # 2) Create a production order for this client order
    r = client.post("/api/planning/create-production-order", json={
        "production_type": "client_order",
        "sales_order_id": so["id"],
        "model_id": 1,
        "planned_quantity": 100,
        "items": [
            {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
            {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 50},
        ],
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    po = r.json()

    # 3) Create work orders
    r = client.post(f"/api/production-orders/{po['id']}/create-work-orders?include_printing=false",
                    headers=auth_headers)
    assert r.status_code == 200
    created = r.json()["created"]
    assert any(c["operation"] == "cutting" for c in created)
    assert any(c["operation"] == "sewing" for c in created)
    assert any(c["operation"] == "packaging" for c in created)

    # Find the cutting WO
    r = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert r.status_code == 200
    wos = r.json()
    cutting_wo = next(w for w in wos if w["operation"] == "cutting")
    sewing_wo = next(w for w in wos if w["operation"] == "sewing")
    packaging_wo = next(w for w in wos if w["operation"] == "packaging")

    # 4) Cutting record + bundles
    r = client.post("/api/cutting/records", json={
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
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    bundles = r.json()["bundles"]
    assert len(bundles) == 2

    # 5) Bundle scan: send + receive sewing
    b1 = bundles[0]
    r = client.post(f"/api/bundles/{b1['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200
    r = client.post(f"/api/bundles/{b1['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "received_sewing"

    # Sewing record (input <= cutting passed)
    r = client.post("/api/sewing/records", json={
        "work_order_id": sewing_wo["id"],
        "input_qty": 100,
        "sewn_qty": 100,
        "passed_qty": 95,
        "failed_qty": 5,
    }, headers=auth_headers)
    assert r.status_code == 201, r.text

    # Packaging record
    r = client.post("/api/packaging/records", json={
        "work_order_id": packaging_wo["id"],
        "input_qty": 95,
        "packed_qty": 90,
        "damaged_qty": 5,
    }, headers=auth_headers)
    assert r.status_code == 201, r.text

    # 6) Create a package (mixed sizes, capacity 60)
    r = client.post("/api/packages", json={
        "production_order_id": po["id"],
        "sales_order_id": so["id"],
        "model_id": 1,
        "color": "white",
        "package_type": "bag",
        "capacity": 60,
        "items": [
            {"model_id": 1, "color": "white", "size": "M", "quantity": 30},
            {"model_id": 1, "color": "white", "size": "L", "quantity": 30},
        ],
    }, headers=auth_headers)
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert pkg["total_quantity"] == 60
    assert pkg["barcode"]

    # 7) Receive at storage by scanning
    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "received_in_storage"


def test_package_over_capacity_blocked_without_admin_override(client, auth_headers):
    """Default user cannot exceed 60 pcs. (Admin can override via override_capacity flag.)"""
    # Use seed model_id=1 + a fresh PO
    r = client.post("/api/planning/create-production-order", json={
        "production_type": "client_order",
        "sales_order_id": 1, "model_id": 1, "planned_quantity": 100,
        "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
    }, headers=auth_headers)
    assert r.status_code == 201
    po_id = r.json()["id"]

    r = client.post("/api/packages", json={
        "production_order_id": po_id,
        "model_id": 1, "color": "white", "package_type": "bag",
        "capacity": 60,
        "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 70}],
    }, headers=auth_headers)
    # admin has override allowed but override_capacity=False by default → still blocked
    assert r.status_code == 400


def test_branded_production_requires_approved_model(client, auth_headers):
    # Create a draft model
    r = client.post("/api/models", json={"code": "DRAFT-001", "name": "Draft model", "status": "draft"}, headers=auth_headers)
    assert r.status_code == 201
    mid = r.json()["id"]
    r = client.post("/api/planning/create-branded-production", json={
        "production_type": "branded_stock", "model_id": mid, "planned_quantity": 10, "items": []
    }, headers=auth_headers)
    assert r.status_code == 400
