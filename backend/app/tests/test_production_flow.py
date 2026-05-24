"""Integration tests for core production flow endpoints."""
from datetime import datetime, timedelta, timezone


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
