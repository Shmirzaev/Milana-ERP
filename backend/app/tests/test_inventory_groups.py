def test_inventory_stock_groups_separate_materials_and_accessories(client, auth_headers):
    material_response = client.get("/api/inventory/stock?group=materials", headers=auth_headers)
    accessory_response = client.get("/api/inventory/stock?group=accessories", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text

    material_skus = {row["item_sku"] for row in material_response.json()}
    accessory_skus = {row["item_sku"] for row in accessory_response.json()}

    assert "FAB-COT-001" in material_skus
    assert "FAB-POL-001" in material_skus
    assert "ACC-BTN-001" not in material_skus
    assert "ACC-BTN-001" in accessory_skus
    assert "ACC-ZIP-001" in accessory_skus
    assert "FAB-COT-001" not in accessory_skus


def test_inventory_item_groups_follow_same_split(client, auth_headers):
    material_response = client.get("/api/inventory/items?group=materials", headers=auth_headers)
    accessory_response = client.get("/api/inventory/items?group=accessories", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text

    material_categories = {row["category"] for row in material_response.json()}
    accessory_categories = {row["category"] for row in accessory_response.json()}

    assert material_categories <= {"fabric", "semi_finished"}
    assert accessory_categories <= {"accessory", "packaging"}


def test_inventory_stock_search_filters_within_group(client, auth_headers):
    material_response = client.get("/api/inventory/stock?group=materials&q=cot", headers=auth_headers)
    accessory_response = client.get("/api/inventory/stock?group=accessories&q=zip", headers=auth_headers)
    crossed_response = client.get("/api/inventory/stock?group=accessories&q=fab", headers=auth_headers)

    assert material_response.status_code == 200, material_response.text
    assert accessory_response.status_code == 200, accessory_response.text
    assert crossed_response.status_code == 200, crossed_response.text

    material_skus = {row["item_sku"] for row in material_response.json()}
    accessory_skus = {row["item_sku"] for row in accessory_response.json()}
    crossed_skus = {row["item_sku"] for row in crossed_response.json()}

    assert "FAB-COT-001" in material_skus
    assert "FAB-POL-001" not in material_skus
    assert "ACC-ZIP-001" in accessory_skus
    assert "ACC-BTN-001" not in accessory_skus
    assert all(not sku.startswith("FAB-") for sku in crossed_skus)


def test_accessory_issue_plan_records_po_model_outgoing_counts(client, auth_headers):
    items_response = client.get("/api/inventory/items?group=accessories", headers=auth_headers)
    assert items_response.status_code == 200, items_response.text
    thread = next(row for row in items_response.json() if row["sku"] == "ACC-THR-001")

    warehouses_response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses_response.status_code == 200, warehouses_response.text
    accessory_warehouse = next(row for row in warehouses_response.json() if row["type"] == "accessory_storage")

    receive_response = client.post(
        "/api/inventory/receive",
        json={
            "item_id": thread["id"],
            "batch_no": "B-ACC-ISSUE-001",
            "quantity": 10,
            "unit": "roll",
            "cost_per_unit": 1.2,
            "warehouse_id": accessory_warehouse["id"],
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert receive_response.status_code == 201, receive_response.text

    po_response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 100,
            "items": [],
        },
        headers=auth_headers,
    )
    assert po_response.status_code == 201, po_response.text
    po = po_response.json()

    plan_response = client.get(
        f"/api/inventory/accessory-issue-plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    thread_plan = next(row for row in plan["rows"] if row["item_sku"] == "ACC-THR-001")
    assert round(float(thread_plan["required_quantity"]), 2) == 2.10
    assert round(float(thread_plan["remaining_quantity"]), 2) == 2.10

    issue_response = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": po["id"],
            "lines": [{"item_id": thread["id"], "quantity": 2.1, "unit": "roll"}],
        },
        headers=auth_headers,
    )
    assert issue_response.status_code == 201, issue_response.text
    assert round(float(issue_response.json()["issued"][0]["quantity"]), 2) == 2.10

    summary_response = client.get(
        f"/api/inventory/accessory-issues?production_order_id={po['id']}&model_id=1",
        headers=auth_headers,
    )
    assert summary_response.status_code == 200, summary_response.text
    summary_row = next(row for row in summary_response.json() if row["item_sku"] == "ACC-THR-001")
    assert summary_row["production_order_id"] == po["id"]
    assert summary_row["model_code"] == "T-SHIRT-001"
    assert round(float(summary_row["issued_quantity"]), 2) == 2.10

    refreshed_plan_response = client.get(
        f"/api/inventory/accessory-issue-plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert refreshed_plan_response.status_code == 200, refreshed_plan_response.text
    refreshed_thread = next(row for row in refreshed_plan_response.json()["rows"] if row["item_sku"] == "ACC-THR-001")
    assert round(float(refreshed_thread["issued_quantity"]), 2) == 2.10
    assert round(float(refreshed_thread["remaining_quantity"]), 2) == 0.00

    stock_response = client.get("/api/inventory/stock?group=accessories&q=ACC-THR-001", headers=auth_headers)
    assert stock_response.status_code == 200, stock_response.text
    stock_row = next(row for row in stock_response.json() if row["item_sku"] == "ACC-THR-001")
    assert round(float(stock_row["quantity"]), 2) == 7.90
