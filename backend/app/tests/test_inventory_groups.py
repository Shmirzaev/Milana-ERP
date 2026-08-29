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


def test_inventory_receiving_rejects_crossed_storage_groups(client, auth_headers):
    material_items = client.get("/api/inventory/items?group=materials", headers=auth_headers).json()
    accessory_items = client.get("/api/inventory/items?group=accessories", headers=auth_headers).json()
    warehouses = client.get("/api/inventory/warehouses", headers=auth_headers).json()
    fabric = next(row for row in material_items if row["category"] == "fabric")
    accessory = next(row for row in accessory_items if row["category"] == "accessory")
    fabric_storage = next(row for row in warehouses if row["type"] == "fabric_storage")
    accessory_storage = next(row for row in warehouses if row["type"] == "accessory_storage")

    cases = (
        (fabric, accessory_storage, "Fabric Storage"),
        (accessory, fabric_storage, "Accessory Storage"),
    )
    for index, (item, warehouse, expected_storage) in enumerate(cases, start=1):
        response = client.post(
            "/api/inventory/receive",
            json={
                "item_id": item["id"],
                "batch_no": f"CROSSED-STORAGE-{index}",
                "quantity": 1,
                "unit": item["unit"],
                "cost_per_unit": 1,
                "warehouse_id": warehouse["id"],
                "qc_status": "passed",
            },
            headers=auth_headers,
        )
        assert response.status_code == 400, response.text
        assert expected_storage in response.json()["detail"]


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
    assert round(float(summary_row["returnable_quantity"]), 2) == 2.10

    return_response = client.post(
        "/api/inventory/accessory-returns",
        json={
            "production_order_id": po["id"],
            "item_id": thread["id"],
            "batch_no": "B-ACC-RETURN-001",
            "quantity": 1.1,
            "unit": "roll",
            "cost_per_unit": 0,
            "warehouse_id": accessory_warehouse["id"],
            "qc_status": "passed",
            "return_condition": "used",
        },
        headers=auth_headers,
    )
    assert return_response.status_code == 201, return_response.text
    assert return_response.json()["order_no"] == (po.get("order_no") or po["production_no"])

    returned_summary_response = client.get(
        f"/api/inventory/accessory-issues?production_order_id={po['id']}&model_id=1",
        headers=auth_headers,
    )
    assert returned_summary_response.status_code == 200, returned_summary_response.text
    returned_summary_row = next(row for row in returned_summary_response.json() if row["item_sku"] == "ACC-THR-001")
    assert round(float(returned_summary_row["issued_quantity"]), 2) == 2.10
    assert round(float(returned_summary_row["returned_quantity"]), 2) == 1.10
    assert round(float(returned_summary_row["returnable_quantity"]), 2) == 1.00

    over_return_response = client.post(
        "/api/inventory/accessory-returns",
        json={
            "production_order_id": po["id"],
            "item_id": thread["id"],
            "batch_no": "B-ACC-RETURN-002",
            "quantity": 1.1,
            "unit": "roll",
            "cost_per_unit": 0,
            "warehouse_id": accessory_warehouse["id"],
            "qc_status": "passed",
            "return_condition": "used",
        },
        headers=auth_headers,
    )
    assert over_return_response.status_code == 409, over_return_response.text

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
    assert round(float(stock_row["quantity"]), 2) == 9.00


def test_accessory_issue_allows_extra_non_bom_accessory(client, auth_headers):
    extra_item_response = client.post(
        "/api/inventory/items",
        json={
            "sku": "ACC-EXTRA-ISSUE-001",
            "name": "Extra issue accessory",
            "category": "accessory",
            "unit": "pcs",
            "default_cost": 0.25,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert extra_item_response.status_code == 201, extra_item_response.text
    extra_item = extra_item_response.json()

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
    assert extra_item["id"] not in {row["item_id"] for row in plan_response.json()["rows"]}

    warehouses_response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses_response.status_code == 200, warehouses_response.text
    accessory_warehouse = next(row for row in warehouses_response.json() if row["type"] == "accessory_storage")

    receive_response = client.post(
        "/api/inventory/receive",
        json={
            "item_id": extra_item["id"],
            "batch_no": "B-ACC-EXTRA-ISSUE-001",
            "quantity": 8,
            "unit": "pcs",
            "cost_per_unit": 0.25,
            "warehouse_id": accessory_warehouse["id"],
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert receive_response.status_code == 201, receive_response.text

    issue_response = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": po["id"],
            "lines": [{"item_id": extra_item["id"], "quantity": 3, "unit": "pcs"}],
        },
        headers=auth_headers,
    )
    assert issue_response.status_code == 201, issue_response.text
    assert issue_response.json()["issued"][0]["item_sku"] == "ACC-EXTRA-ISSUE-001"

    summary_response = client.get(
        f"/api/inventory/accessory-issues?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert summary_response.status_code == 200, summary_response.text
    summary_row = next(row for row in summary_response.json() if row["item_sku"] == "ACC-EXTRA-ISSUE-001")
    assert summary_row["production_order_id"] == po["id"]
    assert round(float(summary_row["issued_quantity"]), 2) == 3.00


def test_manual_accessory_issue_does_not_require_inventory_stock(client, auth_headers):
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

    issue_response = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": po["id"],
            "lines": [
                {
                    "item_sku": "145-IP",
                    "item_name": "145-IP",
                    "quantity": 24,
                    "unit": "pcs",
                    "manual": True,
                }
            ],
        },
        headers=auth_headers,
    )
    assert issue_response.status_code == 201, issue_response.text
    issued = issue_response.json()["issued"][0]
    assert issued["item_id"] == 0
    assert issued["item_sku"] == "145-IP"
    assert round(float(issued["quantity"]), 2) == 24.00

    summary_response = client.get(
        f"/api/inventory/accessory-issues?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert summary_response.status_code == 200, summary_response.text
    summary_row = next(row for row in summary_response.json() if row["item_sku"] == "145-IP")
    assert summary_row["item_id"] == 0
    assert round(float(summary_row["issued_quantity"]), 2) == 24.00

    stock_response = client.get("/api/inventory/stock?group=accessories&q=145-IP", headers=auth_headers)
    assert stock_response.status_code == 200, stock_response.text
    assert stock_response.json() == []


def test_accessory_requests_block_sewing_until_issued_after_cutting(client, auth_headers):
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

    work_orders = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    cutting_wo = next(row for row in work_orders.json() if row["operation"] == "cutting")
    sewing_wo = next(row for row in work_orders.json() if row["operation"] == "sewing")

    cut = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 1, "next": "sewing"},
            ],
        },
        headers=auth_headers,
    )
    assert cut.status_code == 201, cut.text
    bundle_id = cut.json()["bundles"][0]["id"]

    requests = client.get(
        f"/api/inventory/accessory-issue-requests?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert requests.status_code == 200, requests.text
    request_rows = requests.json()
    assert request_rows
    assert any(float(row["remaining_quantity"]) > 0 for row in request_rows)

    blocked_start = client.post(f"/api/work-orders/{sewing_wo['id']}/start", headers=auth_headers)
    assert blocked_start.status_code == 409, blocked_start.text
    assert "Accessories must be issued before sewing" in blocked_start.text

    blocked_receive = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert blocked_receive.status_code == 409, blocked_receive.text
    assert "Accessories must be issued before sewing" in blocked_receive.text

    warehouses_response = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses_response.status_code == 200, warehouses_response.text
    accessory_warehouse = next(row for row in warehouses_response.json() if row["type"] == "accessory_storage")

    plan_response = client.get(
        f"/api/inventory/accessory-issue-plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    plan_rows = plan_response.json()["rows"]
    assert plan_rows

    for row in plan_rows:
        receive = client.post(
            "/api/inventory/receive",
            json={
                "item_id": row["item_id"],
                "batch_no": f"ACC-BLOCK-{po['id']}-{row['item_id']}",
                "quantity": float(row["remaining_quantity"]) + 1,
                "unit": row["unit"],
                "cost_per_unit": 1,
                "warehouse_id": accessory_warehouse["id"],
                "qc_status": "passed",
            },
            headers=auth_headers,
        )
        assert receive.status_code == 201, receive.text

    issue = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": po["id"],
            "lines": [
                {"item_id": row["item_id"], "quantity": row["remaining_quantity"], "unit": row["unit"]}
                for row in plan_rows
                if float(row["remaining_quantity"]) > 0
            ],
        },
        headers=auth_headers,
    )
    assert issue.status_code == 201, issue.text

    refreshed_plan = client.get(
        f"/api/inventory/accessory-issue-plan?production_order_id={po['id']}",
        headers=auth_headers,
    )
    assert refreshed_plan.status_code == 200, refreshed_plan.text
    assert refreshed_plan.json()["is_complete"] is True

    started = client.post(f"/api/work-orders/{sewing_wo['id']}/start", headers=auth_headers)
    assert started.status_code == 200, started.text

    received = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert received.status_code == 200, received.text
