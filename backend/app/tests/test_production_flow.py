"""Integration tests for core production flow endpoints."""
import base64
import pytest
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

_VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


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


def _issue_required_accessories(client, headers, production_order_id: int) -> None:
    plan_response = client.get(
        f"/api/inventory/accessory-issue-plan?production_order_id={production_order_id}",
        headers=headers,
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    rows = [row for row in plan["rows"] if float(row["remaining_quantity"] or 0) > 0]
    if not rows:
        return

    warehouses_response = client.get("/api/inventory/warehouses", headers=headers)
    assert warehouses_response.status_code == 200, warehouses_response.text
    accessory_warehouse = next(row for row in warehouses_response.json() if row["type"] == "accessory_storage")

    for row in rows:
        shortage = max(0.0, float(row["remaining_quantity"] or 0) - float(row["available_quantity"] or 0))
        if shortage <= 0:
            continue
        receive = client.post(
            "/api/inventory/receive",
            json={
                "item_id": row["item_id"],
                "batch_no": f"ACC-AUTO-{production_order_id}-{row['item_id']}-{uuid4().hex[:8].upper()}",
                "quantity": shortage + 1,
                "unit": row["unit"],
                "cost_per_unit": 1,
                "warehouse_id": accessory_warehouse["id"],
                "qc_status": "passed",
            },
            headers=headers,
        )
        assert receive.status_code == 201, receive.text

    issue = client.post(
        "/api/inventory/accessory-issues",
        json={
            "production_order_id": production_order_id,
            "lines": [
                {"item_id": row["item_id"], "quantity": row["remaining_quantity"], "unit": row["unit"]}
                for row in rows
            ],
        },
        headers=headers,
    )
    assert issue.status_code == 201, issue.text


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


def test_branded_production_can_store_printing_details(client, auth_headers):
    upload = client.post(
        "/api/production-orders/printing-attachments/upload",
        files={"file": ("branded-print.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    attachment = upload.json()
    assert attachment["file_url"].startswith("/storage/sales-order-files/")
    assert "sig=" in attachment["file_url"]

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 80,
            "printing_instructions": "Front chest logo, use approved artwork.",
            "printing_attachments": [attachment],
            "items": [
                {
                    "model_id": 1,
                    "color": "white",
                    "size": "M",
                    "planned_quantity": 80,
                    "printing_required": True,
                },
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["printing_instructions"] == "Front chest logo, use approved artwork."
    assert created["printing_attachments"][0]["file_url"] == attachment["file_url"].split("?", 1)[0]
    po_id = int(created["id"])

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["printing_instructions"] == "Front chest logo, use approved artwork."
    assert po["printing_attachments"][0]["file_url"].startswith("/storage/sales-order-files/")
    assert "sig=" in po["printing_attachments"][0]["file_url"]
    assert po["items"][0]["printing_required"] is True
    operations = {row["operation"] for row in po["work_orders"]}
    assert "printing" in operations


def test_branded_production_assigns_selected_sewing_factory(client, auth_headers):
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 60,
            "sewing_factory_code": "BST",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text

    detail = client.get(
        f"/api/production-orders/{response.json()['id']}",
        headers=auth_headers,
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["sewing_factory_code"] == "BST"

    departments = client.get("/api/departments", headers=auth_headers)
    assert departments.status_code == 200, departments.text
    department_code_by_id = {row["id"]: row["code"] for row in departments.json()}
    sewing_work_order = next(row for row in payload["work_orders"] if row["operation"] == "sewing")
    assert department_code_by_id[sewing_work_order["department_id"]] == "BST"


def test_packaging_cannot_start_before_sewing_has_output(client, auth_headers):
    response = client.post(
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
    assert response.status_code == 201, response.text
    production_order_id = response.json()["id"]

    work_orders = client.get(
        f"/api/work-orders?production_order_id={production_order_id}",
        headers=auth_headers,
    )
    assert work_orders.status_code == 200, work_orders.text
    by_operation = {row["operation"]: row for row in work_orders.json()}

    blocked = client.post(
        f"/api/work-orders/{by_operation['packaging']['id']}/start",
        headers=auth_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert "cannot start until sewing has passed output" in blocked.json()["detail"]

    cutting_start = client.post(
        f"/api/work-orders/{by_operation['cutting']['id']}/start",
        headers=auth_headers,
    )
    assert cutting_start.status_code == 200, cutting_start.text
    assert cutting_start.json()["status"] == "in_progress"


def test_printable_bundle_and_package_qr_labels_include_material_picture(client, auth_headers):
    model_code = f"QR-MAT-{uuid4().hex[:8].upper()}"
    model = client.post(
        "/api/models",
        json={
            "code": model_code,
            "name": "QR material label model",
            "category": "T-shirt",
            "status": "approved",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = int(model.json()["id"])

    upload = client.post(
        f"/api/models/{model_id}/images/upload",
        data={"image_type": "material"},
        files={"file": ("material.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text

    po = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 60,
            "items": [
                {"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert po.status_code == 201, po.text
    po_id = int(po.json()["id"])

    bundle = client.post(
        "/api/bundles",
        json={
            "production_order_id": po_id,
            "model_id": model_id,
            "color": "white",
            "size": "M",
            "quantity": 60,
        },
        headers=auth_headers,
    )
    assert bundle.status_code == 201, bundle.text
    bundle_id = int(bundle.json()["id"])

    package = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": model_id,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [
                {"model_id": model_id, "color": "white", "size": "M", "quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert package.status_code == 201, package.text
    package_id = int(package.json()["id"])

    endpoints = [
        f"/api/bundles/{bundle_id}/label",
        f"/api/bundles/label-sheet/by-ids?ids={bundle_id}",
        f"/api/packages/{package_id}/label",
        f"/api/packages/label-sheet/by-ids?ids={package_id}",
    ]
    for endpoint in endpoints:
        label = client.get(endpoint, headers=auth_headers)
        assert label.status_code == 200, label.text
        assert "material-picture" in label.text
        assert "alt='Material picture'" in label.text or 'alt="Material picture"' in label.text
        assert "data:image/png;base64" in label.text
        if endpoint == f"/api/packages/{package_id}/label":
            assert ".qr img{display:block;width:50mm;height:50mm" in label.text
        if endpoint == f"/api/packages/label-sheet/by-ids?ids={package_id}":
            assert "@page{size:A4;margin:6mm}" in label.text
            assert "width:96mm;height:132mm" in label.text
            assert ".qr img{display:block;width:45mm;height:45mm" in label.text
            assert ".material-picture img{display:block;width:25mm;height:25mm" in label.text


def test_cutting_record_print_sheet_keeps_all_reference_sections(client, auth_headers):
    selected_brand = client.post(
        "/api/brands",
        json={"name": "Planner Selected Brand", "is_active": True},
        headers=auth_headers,
    )
    assert selected_brand.status_code == 201, selected_brand.text
    selected_brand_id = int(selected_brand.json()["id"])

    material_upload = client.post(
        "/api/models/1/images/upload",
        data={"image_type": "material"},
        files={"file": ("cutting-sheet-material.png", _VALID_PNG, "image/png")},
        headers=auth_headers,
    )
    assert material_upload.status_code == 201, material_upload.text

    production = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "brand_id": selected_brand_id,
            "planned_quantity": 100,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 50},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 50},
            ],
            "batches": [{"name": "Cutting sheet batch", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert production.status_code == 201, production.text
    assert production.json()["brand_id"] == selected_brand_id
    production_order_id = int(production.json()["id"])
    production_detail = client.get(f"/api/production-orders/{production_order_id}", headers=auth_headers)
    assert production_detail.status_code == 200, production_detail.text
    production_batch_id = int(production_detail.json()["batches"][0]["id"])

    work_orders = client.get(
        f"/api/work-orders?production_order_id={production_order_id}",
        headers=auth_headers,
    )
    assert work_orders.status_code == 200, work_orders.text
    cutting_work_order = next(row for row in work_orders.json() if row["operation"] == "cutting")

    cutting = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_work_order["id"],
            "production_batch_id": production_batch_id,
            "fabric_batch_id": None,
            "input_quantity": 100,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "beika_kg": 2.5,
            "layup_operator_name": "Aziza Opa",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 50, "count": 1},
                {"color": "white", "size": "L", "quantity": 50, "count": 1},
            ],
        },
        headers=auth_headers,
    )
    assert cutting.status_code == 201, cutting.text
    body = cutting.json()
    record_id = int(body["id"])
    bundle_ids = ",".join(str(row["id"]) for row in body["bundles"])

    sheet = client.get(
        f"/api/cutting/records/{record_id}/production-sheet?bundle_ids={bundle_ids}",
        headers=auth_headers,
    )
    assert sheet.status_code == 200, sheet.text
    assert sheet.headers["content-type"].startswith("text/html")
    assert "T-SHIRT-001" in sheet.text
    assert "Planner Selected Brand" in sheet.text
    assert ">M<" in sheet.text and ">L<" in sheet.text
    assert "2.5 kg" in sheet.text
    assert "Nastilchi" in sheet.text
    assert "Aziza Opa" in sheet.text
    for section in (
        "Model",
        "Qolip No",
        "Artikul",
        "Zakaz No",
        "Bichilgan sana",
        "Etiket",
        "Kroy No",
        "Detskiy",
        "Sana",
        "Buyurtma soni",
        "Bichilgan soni",
        "Razmer",
        "Buyurtma",
        "Kesildi",
        "Pechat",
        "Tikuv",
        "2-sort",
        "Dazmol",
        "Brak",
        "Upakovka",
        "Tesma",
        "Tugma",
        "Zamok",
        "Ribana",
        "Razmer etiket",
        "Beyka",
        "Kurjava",
        "IP",
        "Mato turi",
        "Fabrika nomi",
        "Mato namuna",
        "Beyka namuna",
    ):
        assert section in sheet.text
    assert "None" not in sheet.text
    assert "class=\"sample-box fabric-sample\"" in sheet.text
    assert "grid-template-rows:minmax(0,1fr) minmax(0,1fr)" in sheet.text
    assert "grid-template-rows:9mm minmax(0,1fr) 9mm minmax(0,1fr)" in sheet.text
    assert "class=\"sample-title print\">Pechat</div>" in sheet.text
    assert "alt='Fabric picture'" in sheet.text
    assert "data:image/png;base64" in sheet.text
    assert "Sewing batch acceptance QR" in sheet.text
    assert f"/bundles/scan/sewing?batch={production_batch_id}" in sheet.text

    invalid = client.get(
        f"/api/cutting/records/{record_id}/production-sheet?bundle_ids=not-a-number",
        headers=auth_headers,
    )
    assert invalid.status_code == 400, invalid.text


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


def test_standalone_production_order_keeps_explicit_process_reference_fields(client, auth_headers):
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

    passport_no = f"KR-{po['id']}"
    r = client.post(
        "/api/cutting-passports",
        json={
            "passport_no": passport_no,
            "date": datetime.now(timezone.utc).isoformat(),
            "production_order_id": po["id"],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    wos = r.json()
    assert wos

    r = client.get(f"/api/process-tracking?q={po['production_no']}&include_total=true&page_size=10", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    tracked = next(row for row in rows if row["production_order_id"] == po["id"])
    assert tracked["production_no"] == po["production_no"]
    assert tracked["sales_order_no"] is None
    assert tracked["sizes"] == [{"size": "M", "planned_quantity": 60, "completed_quantity": 0}]
    assert tracked["cutting_passport_no"] == passport_no
    assert tracked["cutting_passports"][0]["passport_no"] == passport_no


def test_process_tracking_new_waiting_order_starts_at_cutting(client, auth_headers):
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

    from app.db.session import SessionLocal
    from app.models import ProductionOrder, WorkOrder

    db = SessionLocal()
    try:
        row = db.get(ProductionOrder, po["id"])
        row.status = "planning"
        for wo in db.query(WorkOrder).filter(WorkOrder.production_order_id == po["id"]).all():
            wo.status = "waiting"
            wo.actual_input_qty = 0
            wo.actual_output_qty = 0
            wo.passed_qty = 0
            wo.failed_qty = 0
            wo.rework_qty = 0
            wo.start_time = None
            wo.end_time = None
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/process-tracking?q={po['production_no']}&include_total=true&page_size=10", headers=auth_headers)
    assert r.status_code == 200, r.text
    tracked = next(row for row in r.json()["rows"] if row["production_order_id"] == po["id"])
    assert tracked["current_stage"] == "cutting"
    assert tracked["current_stage_status"] == "waiting"
    assert {stage["operation"]: stage["status"] for stage in tracked["stages"]}["storage_transfer"] == "waiting"


def test_packaging_receives_sewing_work_by_scan_and_manual_entry(client, auth_headers):
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 20,
            "items": [
                {"model_id": 1, "color": "navy", "size": "M", "planned_quantity": 20},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    production_order = response.json()

    from app.db.session import SessionLocal
    from app.models import Bundle, SewingRecord, WorkOrder

    suffix = uuid4().hex[:8]
    db = SessionLocal()
    try:
        sewing_work_order = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order["id"],
            WorkOrder.operation == "sewing",
        ).one()
        packaging_work_order = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == production_order["id"],
            WorkOrder.operation == "packaging",
        ).one()
        sewing_work_order.actual_output_qty = 20
        sewing_work_order.passed_qty = 20
        db.add(SewingRecord(
            work_order_id=sewing_work_order.id,
            input_qty=20,
            sewn_qty=20,
            passed_qty=20,
            failed_qty=0,
            rework_qty=0,
            rejected_qty=0,
        ))
        bundle = Bundle(
            bundle_no=f"BND-PKG-{suffix}",
            barcode=f"PKG-RECEIVE-{suffix}",
            production_order_id=production_order["id"],
            model_id=1,
            color="navy",
            size="M",
            quantity=10,
            status="received_sewing",
        )
        db.add(bundle)
        db.commit()
        db.refresh(bundle)
        packaging_work_order_id = packaging_work_order.id
        bundle_barcode = bundle.barcode
    finally:
        db.close()

    options = client.get(
        f"/api/packaging/receive-options?q={production_order['production_no']}",
        headers=auth_headers,
    )
    assert options.status_code == 200, options.text
    option = next(row for row in options.json() if row["work_order_id"] == packaging_work_order_id)
    assert option["sewing_passed"] == 20
    assert option["received_quantity"] == 0
    assert option["available_quantity"] == 20

    manual = client.post(
        "/api/packaging/receive-from-sewing",
        json={"work_order_id": packaging_work_order_id, "quantity": 7},
        headers=auth_headers,
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["receive_method"] == "manual"
    assert manual.json()["remaining_available"] == 13

    scanned = client.post(
        "/api/packaging/receive-from-sewing",
        json={"bundle_code": bundle_barcode},
        headers=auth_headers,
    )
    assert scanned.status_code == 201, scanned.text
    assert scanned.json()["receive_method"] == "scan"
    assert scanned.json()["bundle_no"].startswith("BND-PKG-")
    assert scanned.json()["remaining_available"] == 3

    duplicate = client.post(
        "/api/packaging/receive-from-sewing",
        json={"bundle_code": bundle_barcode},
        headers=auth_headers,
    )
    assert duplicate.status_code == 409, duplicate.text

    over_receive = client.post(
        "/api/packaging/receive-from-sewing",
        json={"work_order_id": packaging_work_order_id, "quantity": 4},
        headers=auth_headers,
    )
    assert over_receive.status_code == 400, over_receive.text

    over_pack = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_work_order_id,
            "input_qty": 18,
            "packed_qty": 18,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert over_pack.status_code == 400, over_pack.text
    assert "received from sewing 17" in over_pack.text

    receipts = client.get("/api/packaging/receipts?limit=10", headers=auth_headers)
    assert receipts.status_code == 200, receipts.text
    matching = [row for row in receipts.json() if row["production_order_id"] == production_order["id"]]
    assert [row["receive_method"] for row in matching[:2]] == ["scan", "manual"]

    received_orders = client.get("/api/packaging/received-orders", headers=auth_headers)
    assert received_orders.status_code == 200, received_orders.text
    received_order = next(
        row for row in received_orders.json() if row["production_order_id"] == production_order["id"]
    )
    assert received_order["work_order_id"] == packaging_work_order_id
    assert received_order["received_quantity"] == 17
    assert received_order["packing_input_quantity"] == 0
    assert received_order["remaining_quantity"] == 17
    assert "model_image_url" in received_order

    db = SessionLocal()
    try:
        packaging_work_order = db.get(WorkOrder, packaging_work_order_id)
        assert packaging_work_order.actual_input_qty == 17
        assert packaging_work_order.status == "collected"
    finally:
        db.close()


def test_zero_quantity_storage_transfer_does_not_override_cutting(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()

    r = client.get(f"/api/work-orders?production_order_id={po['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    storage_wo = next(row for row in r.json() if row["operation"] == "storage_transfer")
    start_storage = client.post(f"/api/work-orders/{storage_wo['id']}/start", headers=auth_headers)
    assert start_storage.status_code == 400, start_storage.text

    from app.db.session import SessionLocal
    from app.models import ProductionOrder, WorkOrder
    from app.services.workflow import sync_production_order_status

    db = SessionLocal()
    try:
        po_row = db.get(ProductionOrder, po["id"])
        po_row.status = "storage_transfer"
        for wo in db.query(WorkOrder).filter(WorkOrder.production_order_id == po["id"]).all():
            if wo.operation == "cutting":
                wo.status = "in_progress"
                wo.start_time = datetime.now(timezone.utc)
            elif wo.operation == "storage_transfer":
                wo.status = "in_progress"
                wo.start_time = datetime.now(timezone.utc)
                wo.actual_input_qty = 12
                wo.actual_output_qty = 0
                wo.passed_qty = 0
                wo.failed_qty = 0
                wo.rework_qty = 0
        sync_production_order_status(db, po["id"])
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/process-tracking?q={po['production_no']}&include_total=true&page_size=10", headers=auth_headers)
    assert r.status_code == 200, r.text
    tracked = next(row for row in r.json()["rows"] if row["production_order_id"] == po["id"])
    assert tracked["po_status"] == "cutting"
    assert tracked["current_stage"] == "cutting"
    assert tracked["current_stage_status"] == "in_progress"
    statuses = {stage["operation"]: stage["status"] for stage in tracked["stages"]}
    assert statuses["cutting"] == "in_progress"
    assert statuses["storage_transfer"] == "waiting"


def test_production_order_detail_includes_estimated_material_composition(client, auth_headers):
    item = client.post(
        "/api/inventory/items",
        json={
            "sku": "FAB-ORDER-COMP",
            "name": "Order composition fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 3,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "composition": [
                {"name": "Viscose", "percentage": 70},
                {"name": "Polyester", "percentage": 30},
            ],
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 80,
            "estimated_material_code": "FAB-ORDER-COMP",
            "estimated_material_amount": 40,
            "estimated_material_unit": "kg",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 80},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    po_id = created.json()["id"]

    detail = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["estimated_material_composition"] == [
        {"name": "Viscose", "percentage": 70.0},
        {"name": "Polyester", "percentage": 30.0},
    ]


def test_process_tracking_pagination_search_status_contract(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    image_url = f"https://example.com/process-{suffix}.png"
    image = client.post(
        "/api/models/1/images",
        json={
            "file_url": image_url,
            "file_name": f"process-{suffix}.png",
            "content_type": "image/png",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert image.status_code == 201, image.text

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 12,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 12},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()

    from app.db.session import SessionLocal
    from app.models import ProductionOrder

    db = SessionLocal()
    try:
        row = db.get(ProductionOrder, po["id"])
        row.production_no = f"PO-PTRACK-{suffix}"
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/process-tracking?include_total=true&page_size=1&q=PO-PTRACK-{suffix}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert set(["rows", "total", "page", "page_size"]).issubset(payload.keys())
    assert payload["page"] == 1
    assert payload["page_size"] == 1
    assert payload["total"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["production_no"] == f"PO-PTRACK-{suffix}"
    assert payload["rows"][0]["model_image_url"] == image_url

    status = payload["rows"][0]["po_status"]
    r = client.get(
        f"/api/process-tracking?include_total=true&page_size=5&q=PO-PTRACK-{suffix}&status={status}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    r = client.get(
        f"/api/process-tracking?include_total=true&page_size=5&q=PO-PTRACK-{suffix}&status=cancelled",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0

    exported = client.get("/api/process-tracking/export", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    assert image_url in exported.text


def test_process_tracking_uses_bom_picture_when_model_picture_missing(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    bom_photo_url = f"https://example.com/process-bom-{suffix}.png"
    model = client.post(
        "/api/models",
        json={
            "code": f"PTRACK-BOM-{suffix}",
            "name": "Process tracking BOM image model",
            "category": "T-shirt",
            "status": "approved",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = int(model.json()["id"])

    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"PTRACK-BOM-FAB-{suffix}",
            "name": "Process tracking BOM fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={
            "item_id": int(item.json()["id"]),
            "photo_url": bom_photo_url,
            "quantity_per_piece": 1,
            "unit": "kg",
            "waste_percent": 0,
        },
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 18,
            "items": [
                {"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 18},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    production_no = created.json()["production_no"]

    tracked = client.get(
        f"/api/process-tracking?include_total=true&page_size=1&q={production_no}",
        headers=auth_headers,
    )
    assert tracked.status_code == 200, tracked.text
    rows = tracked.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["model_image_url"] == bom_photo_url
    assert rows[0]["material_image_url"] == bom_photo_url


def test_department_inbox_uses_variant_material_picture_before_shared_bom_picture(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    old_model_url = f"https://example.com/inbox-old-model-{suffix}.png"
    new_model_url = f"https://example.com/inbox-new-model-{suffix}.png"
    item_fabric_url = f"https://example.com/inbox-item-fabric-{suffix}.png"
    bom_fabric_url = f"https://example.com/inbox-bom-fabric-{suffix}.png"
    variant_material_url = f"https://example.com/inbox-variant-material-{suffix}.png"
    model = client.post(
        "/api/models",
        json={
            "code": f"INBOX-IMG-{suffix}",
            "name": "Inbox image model",
            "category": "Robe",
            "status": "approved",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = int(model.json()["id"])

    old_image = client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": old_model_url,
            "file_name": f"inbox-old-model-{suffix}.png",
            "content_type": "image/png",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert old_image.status_code == 201, old_image.text
    new_image = client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": new_model_url,
            "file_name": f"inbox-new-model-{suffix}.png",
            "content_type": "image/png",
            "image_type": "model",
            "is_primary": True,
        },
        headers=auth_headers,
    )
    assert new_image.status_code == 201, new_image.text
    variant_material_image = client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": variant_material_url,
            "file_name": f"inbox-variant-material-{suffix}.png",
            "content_type": "image/png",
            "image_type": "material",
            "is_primary": False,
        },
        headers=auth_headers,
    )
    assert variant_material_image.status_code == 201, variant_material_image.text

    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"INBOX-FAB-{suffix}",
            "name": "Inbox fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "image_url": item_fabric_url,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text

    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={
            "item_id": int(item.json()["id"]),
            "photo_url": bom_fabric_url,
            "quantity_per_piece": 1,
            "unit": "kg",
            "waste_percent": 0,
        },
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 24,
            "items": [
                {"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 24},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    created_payload = created.json()
    po_id = int(created_payload["id"])
    production_no = created_payload["production_no"]
    planning_order_id = int(created_payload["planning_order_id"])

    branded_orders = client.get("/api/planning/branded-orders", headers=auth_headers)
    assert branded_orders.status_code == 200, branded_orders.text
    planning_order = next(
        row for row in branded_orders.json()
        if int(row["id"]) == planning_order_id
    )

    inbox = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert inbox.status_code == 200, inbox.text
    body = inbox.json()
    rows = body["pending_work_orders"] + body["in_progress_work_orders"] + body["active_work_orders"]
    row = next(row for row in rows if row["production_order_id"] == po_id)
    assert row["model_image_url"] == new_model_url
    assert row["material_image_url"] == variant_material_url
    assert row["planning_order_id"] == planning_order_id
    assert row["planning_order_no"] == planning_order["order_no"]
    assert row["planning_order_name"] == planning_order["ordered_for_name"]
    cutting_row = next(
        row for row in body["cutting_work_orders"]
        if row["production_order_id"] == po_id
    )
    assert cutting_row["planning_order_no"] == planning_order["order_no"]
    assert cutting_row["received_bundle_qty"] == 0

    detail = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["model_image_url"] == new_model_url
    assert detail_payload["material_image_url"] == variant_material_url

    tracked = client.get(
        f"/api/process-tracking?include_total=true&page_size=1&q={production_no}",
        headers=auth_headers,
    )
    assert tracked.status_code == 200, tracked.text
    tracked_row = tracked.json()["rows"][0]
    assert tracked_row["model_image_url"] == new_model_url
    assert tracked_row["material_image_url"] == variant_material_url


def test_cutting_inbox_hides_orders_that_progressed_to_other_departments(client, auth_headers):
    def create_order() -> int:
        response = client.post(
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
        assert response.status_code == 201, response.text
        return int(response.json()["id"])

    control_id = create_order()
    downstream_id = create_order()
    packaged_id = create_order()

    from app.db.session import SessionLocal
    from app.models import Package, ProductionOrder, WorkOrder

    db = SessionLocal()
    try:
        downstream_order = db.get(ProductionOrder, downstream_id)
        downstream_order.status = "cutting"
        sewing_work_order = db.query(WorkOrder).filter(
            WorkOrder.production_order_id == downstream_id,
            WorkOrder.operation == "sewing",
        ).one()
        sewing_work_order.status = "in_progress"
        sewing_work_order.start_time = datetime.now(timezone.utc)

        packaged_order = db.get(ProductionOrder, packaged_id)
        packaged_order.status = "cutting"
        package_suffix = uuid4().hex[:12].upper()
        db.add(Package(
            package_no=f"PKG-INBOX-{package_suffix}",
            barcode=f"PKG-INBOX-{package_suffix}",
            packaging_department_code="PKG",
            production_order_id=packaged_id,
            model_id=1,
            color="white",
            package_type="bag",
            total_quantity=20,
            capacity=60,
            status="packed",
        ))
        db.commit()
    finally:
        db.close()

    inbox = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert inbox.status_code == 200, inbox.text
    body = inbox.json()
    visible_ids = {
        int(row["production_order_id"])
        for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders")
        for row in body[key]
    }
    assert control_id in visible_ids
    assert downstream_id not in visible_ids
    assert packaged_id not in visible_ids


def test_production_detail_keeps_variant_picture_and_batch_scoped_work_uses_batch_picture(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    stale_material_url = f"https://example.com/stale-material-{suffix}.png"
    item_fabric_url = f"https://example.com/item-fabric-{suffix}.png"
    batch_fabric_url = f"https://example.com/batch-fabric-{suffix}.png"
    model = client.post(
        "/api/models",
        json={
            "code": f"PO-BATCH-IMG-{suffix}",
            "name": "Production batch image model",
            "category": "Robe",
            "status": "approved",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = int(model.json()["id"])

    stale_material = client.post(
        f"/api/models/{model_id}/images",
        json={
            "file_url": stale_material_url,
            "file_name": f"stale-material-{suffix}.png",
            "content_type": "image/png",
            "image_type": "material",
            "is_primary": False,
        },
        headers=auth_headers,
    )
    assert stale_material.status_code == 201, stale_material.text

    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"PO-BATCH-FAB-{suffix}",
            "name": "Production batch fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
            "image_url": item_fabric_url,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    item_id = int(item.json()["id"])

    warehouses = client.get("/api/inventory/warehouses", headers=auth_headers)
    assert warehouses.status_code == 200, warehouses.text
    warehouse_id = next(row["id"] for row in warehouses.json() if row["type"] == "fabric_storage")
    batch = client.post(
        "/api/inventory/receive",
        json={
            "item_id": item_id,
            "batch_no": f"PO-BATCH-{suffix}",
            "color": "Different pattern",
            "quantity": 10,
            "unit": "kg",
            "cost_per_unit": 1,
            "image_url": batch_fabric_url,
            "warehouse_id": warehouse_id,
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert batch.status_code == 201, batch.text

    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={
            "item_id": item_id,
            "stock_batch_id": int(batch.json()["id"]),
            "quantity_per_piece": 1,
            "unit": "kg",
            "waste_percent": 0,
        },
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    created = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 12,
            "fabric_batch_id": int(batch.json()["id"]),
            "estimated_material_amount": 12,
            "estimated_material_unit": "kg",
            "items": [
                {"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 12},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    po_id = int(created.json()["id"])
    production_no = created.json()["production_no"]

    detail = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["material_image_url"] == stale_material_url
    assert detail_payload["material_image_url"] != batch_fabric_url
    assert detail_payload["material_image_url"] != item_fabric_url

    work_orders = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    cutting_wo = next(row for row in work_orders.json() if row["operation"] == "cutting")
    assert cutting_wo["material_image_url"] == batch_fabric_url

    cutting_detail = client.get(f"/api/work-orders/{cutting_wo['id']}", headers=auth_headers)
    assert cutting_detail.status_code == 200, cutting_detail.text

    tracked = client.get(
        f"/api/process-tracking?include_total=true&page_size=1&q={production_no}",
        headers=auth_headers,
    )
    assert tracked.status_code == 200, tracked.text
    tracked_row = tracked.json()["rows"][0]
    assert tracked_row["material_image_url"] == batch_fabric_url
    assert tracked_row["material_image_url"] != stale_material_url
    assert tracked_row["material_image_url"] != item_fabric_url
    assert cutting_detail.json()["material_image_url"] == batch_fabric_url


def test_process_tracking_keeps_overlapping_production_and_sales_refs_distinct(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    branded_ref = f"PO-OVERLAP-{suffix}"
    sales_ref = f"SO-OVERLAP-{suffix}"

    branded = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 20,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 20}],
        },
        headers=auth_headers,
    )
    assert branded.status_code == 201, branded.text
    branded_id = branded.json()["id"]

    so_id = _create_client_sales_order(client, auth_headers)

    from app.db.session import SessionLocal
    from app.models import ProductionOrder, SalesOrder

    db = SessionLocal()
    try:
        db.get(ProductionOrder, branded_id).production_no = branded_ref
        db.get(SalesOrder, so_id).order_no = sales_ref
        db.commit()
    finally:
        db.close()

    client_po = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 20,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 20}],
        },
        headers=auth_headers,
    )
    assert client_po.status_code == 201, client_po.text
    client_po_id = client_po.json()["id"]

    r = client.get(f"/api/process-tracking?include_total=true&page_size=10&q=OVERLAP-{suffix}", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = {row["production_order_id"]: row for row in r.json()["rows"]}
    assert branded_id in rows
    assert client_po_id in rows
    assert rows[branded_id]["production_no"] == branded_ref
    assert rows[branded_id]["sales_order_no"] is None
    assert rows[client_po_id]["production_no"] == sales_ref
    assert rows[client_po_id]["sales_order_no"] == sales_ref

    exported = client.get("/api/process-tracking/export", headers=auth_headers)
    assert exported.status_code == 200, exported.text
    assert "Production No" in exported.text
    assert "Sales Order No" in exported.text
    assert branded_ref in exported.text
    assert sales_ref in exported.text


def test_package_barcode_lookup_accepts_label_qr_payload(client, auth_headers):
    pkg_id = _create_package_for_change_request(client, auth_headers, quantity=20)

    r = client.get(f"/api/packages/{pkg_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["model_code"]
    assert pkg["model_name"]
    qr_payload = f"PACKAGE:{pkg['package_no']}|{pkg['barcode']}"

    r = client.get(f"/api/packages/barcode/{quote(qr_payload, safe='')}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["id"]) == pkg_id
    assert r.json()["model_code"] == pkg["model_code"]


def test_batch_receive_packages_to_one_storage_cell(client, auth_headers):
    pkg_id_1 = _create_package_for_change_request(client, auth_headers, quantity=20)
    pkg_id_2 = _create_package_for_change_request(client, auth_headers, quantity=30)

    r = client.post(
        "/api/packages/batch/receive-storage",
        json={
            "package_ids": [pkg_id_1, pkg_id_2],
            "storage_cell": "A-01",
            "storage_shelf": "S2",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    packages = sorted(body["packages"], key=lambda row: row["id"])
    assert [row["id"] for row in packages] == sorted([pkg_id_1, pkg_id_2])
    for row in packages:
        assert row["status"] == "received_in_storage"
        assert row["storage_cell"] == "A-01"
        assert row["storage_shelf"] == "S2"
        assert row["model_code"]
        assert row["model_name"]

    r = client.get(f"/api/packages/{pkg_id_1}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["storage_cell"] == "A-01"
    assert detail["storage_shelf"] == "S2"
    assert detail["model_code"]
    assert detail["model_name"]

    r = client.post(
        "/api/packages/batch/place-on-map",
        json={
            "package_ids": [pkg_id_1, pkg_id_2],
            "storage_cell": "B-02",
            "storage_shelf": "S1",
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    packages = sorted(body["packages"], key=lambda row: row["id"])
    assert [row["id"] for row in packages] == sorted([pkg_id_1, pkg_id_2])
    for row in packages:
        assert row["status"] == "received_in_storage"
        assert row["storage_cell"] == "B-02"
        assert row["storage_shelf"] == "S1"

    r = client.get(f"/api/packages/{pkg_id_1}", headers=auth_headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["storage_cell"] == "B-02"
    assert detail["storage_shelf"] == "S1"


def test_batch_place_on_map_moves_more_than_two_packages(client, auth_headers):
    package_ids = [
        _create_package_for_change_request(client, auth_headers, quantity=10 + index)
        for index in range(4)
    ]

    received = client.post(
        "/api/packages/batch/receive-storage",
        json={
            "package_ids": package_ids,
            "storage_cell": "B-01",
            "storage_shelf": "S1",
        },
        headers=auth_headers,
    )
    assert received.status_code == 200, received.text
    assert received.json()["count"] == 4

    moved = client.post(
        "/api/packages/batch/place-on-map",
        json={
            "package_ids": package_ids,
            "storage_cell": "C-03",
            "storage_shelf": "S2",
        },
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["count"] == 4
    assert {int(row["id"]) for row in moved.json()["packages"]} == set(package_ids)
    assert all(row["storage_cell"] == "C-03" for row in moved.json()["packages"])
    assert all(row["storage_shelf"] == "S2" for row in moved.json()["packages"])


def test_batch_place_on_map_rolls_back_every_package_when_one_is_rejected(client, auth_headers):
    package_ids = [
        _create_package_for_change_request(client, auth_headers, quantity=20)
        for _ in range(3)
    ]
    received = client.post(
        "/api/packages/batch/receive-storage",
        json={
            "package_ids": package_ids,
            "storage_cell": "B-01",
            "storage_shelf": "S1",
        },
        headers=auth_headers,
    )
    assert received.status_code == 200, received.text

    damaged = client.post(f"/api/packages/{package_ids[1]}/mark-damaged", headers=auth_headers)
    assert damaged.status_code == 200, damaged.text

    moved = client.post(
        "/api/packages/batch/place-on-map",
        json={
            "package_ids": package_ids,
            "storage_cell": "C-03",
            "storage_shelf": "S2",
        },
        headers=auth_headers,
    )
    assert moved.status_code == 400, moved.text

    first = client.get(f"/api/packages/{package_ids[0]}", headers=auth_headers).json()
    rejected = client.get(f"/api/packages/{package_ids[1]}", headers=auth_headers).json()
    last = client.get(f"/api/packages/{package_ids[2]}", headers=auth_headers).json()
    assert (first["storage_cell"], first["storage_shelf"]) == ("B-01", "S1")
    assert rejected["status"] == "damaged"
    assert rejected["storage_cell"] is None
    assert (last["storage_cell"], last["storage_shelf"]) == ("B-01", "S1")


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


def test_work_order_list_filters_to_sewing_received_orders(client, auth_headers):
    received_bundle = _create_bundle_for_scan(client, auth_headers)
    waiting_bundle = _create_bundle_for_scan(client, auth_headers)

    r = client.post(f"/api/bundles/{received_bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&only_received_sewing=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    po_ids = {int(row["production_order_id"]) for row in rows}
    assert int(received_bundle["production_order_id"]) in po_ids
    assert int(waiting_bundle["production_order_id"]) not in po_ids

    row = next(row for row in rows if int(row["production_order_id"]) == int(received_bundle["production_order_id"]))
    assert int(row["received_bundle_count"]) == 1
    assert int(row["received_bundle_qty"]) == int(received_bundle["quantity"])
    assert "material_image_url" in row


def test_over_cut_bundle_quantity_becomes_downstream_assignment_quantity(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_op = {w["operation"]: w for w in r.json()}
    cutting_wo = by_op["cutting"]
    sewing_wo = by_op["sewing"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundles = r.json()["bundles"]
    assert len(bundles) == 6

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    refreshed = {w["operation"]: w for w in r.json()["work_orders"]}
    assert int(refreshed["cutting"]["planned_output_qty"]) == 600
    for op in ("sewing", "packaging", "storage_transfer"):
        assert int(refreshed[op]["planned_input_qty"]) == 600
        assert int(refreshed[op]["planned_output_qty"]) == 600

    _issue_required_accessories(client, auth_headers, po_id)
    for bundle in bundles:
        r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
        assert r.status_code == 200, r.text

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&only_received_sewing=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    row = next(row for row in r.json() if int(row["production_order_id"]) == po_id)
    assert int(row["received_bundle_qty"]) == 600
    assert int(row["planned_output_qty"]) == 600

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = int(r.json()[0]["id"])

    r = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow_id,
            "quantity": 600,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert int(r.json()["quantity"]) == 600


def test_cutting_sheet_batch_qr_accepts_all_bundles_into_one_sewing_line(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 100,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 40},
            ],
            "batches": [
                {"name": "QR Batch One", "planned_quantity": 60},
                {"name": "QR Batch Two", "planned_quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_one = next(batch for batch in po["batches"] if batch["name"] == "QR Batch One")
    batch_two = next(batch for batch in po["batches"] if batch["name"] == "QR Batch Two")
    cutting_wo = next(work for work in po["work_orders"] if work["operation"] == "cutting")
    sewing_wo = next(work for work in po["work_orders"] if work["operation"] == "sewing")

    bundles_by_batch: dict[int, list[dict]] = {}
    for batch, quantity, count in ((batch_one, 60, 2), (batch_two, 40, 2)):
        r = client.post(
            "/api/cutting/records",
            json={
                "work_order_id": cutting_wo["id"],
                "production_batch_id": batch["id"],
                "fabric_batch_id": None,
                "input_quantity": 20.0,
                "input_unit": "kg",
                "cut_pieces": quantity,
                "passed_pieces": quantity,
                "defective_pieces": 0,
                "waste_quantity": 0,
                "waste_unit": "kg",
                "bundles": [
                    {"color": "white", "size": "M", "quantity": quantity // count, "count": count},
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        bundles_by_batch[int(batch["id"])] = r.json()["bundles"]

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_one, flow_two = r.json()[:2]

    r = client.get(f"/api/bundles/sewing-batches/{batch_one['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["bundle_count"]) == 2
    assert int(r.json()["quantity"]) == 60

    r = client.post(
        f"/api/bundles/sewing-batches/{batch_one['id']}/accept",
        json={"sewing_flow_id": flow_one["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["received_count"]) == 2
    assert int(r.json()["quantity"]) == 60
    assert int(r.json()["sewing_flow_id"]) == int(flow_one["id"])
    assert r.json()["already_accepted"] is False

    for bundle in bundles_by_batch[int(batch_one["id"])]:
        detail = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "received_sewing"
    for bundle in bundles_by_batch[int(batch_two["id"])]:
        detail = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "created"

    r = client.post(
        f"/api/bundles/sewing-batches/{batch_two['id']}/accept",
        json={"sewing_flow_id": flow_two["id"]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["received_count"]) == 2
    assert int(r.json()["sewing_flow_id"]) == int(flow_two["id"])

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/assignments", headers=auth_headers)
    assert r.status_code == 200, r.text
    assignments = {
        int(row["production_batch_id"]): (int(row["sewing_flow_id"]), int(row["quantity"]))
        for row in r.json()
        if int(row.get("production_batch_id") or 0) in {int(batch_one["id"]), int(batch_two["id"])}
    }
    assert assignments == {
        int(batch_one["id"]): (int(flow_one["id"]), 60),
        int(batch_two["id"]): (int(flow_two["id"]), 40),
    }

    duplicate = client.post(
        f"/api/bundles/sewing-batches/{batch_one['id']}/accept",
        json={"sewing_flow_id": flow_one["id"]},
        headers=auth_headers,
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["already_accepted"] is True
    assert int(duplicate.json()["received_count"]) == 0

    conflict = client.post(
        f"/api/bundles/sewing-batches/{batch_one['id']}/accept",
        json={"sewing_flow_id": flow_two["id"]},
        headers=auth_headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert "already assigned" in conflict.text


def test_sewing_assignments_can_be_selected_by_received_batch(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 100,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 40},
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
    sewing_wo = next(w for w in po["work_orders"] if w["operation"] == "sewing")

    bundles = []
    for batch, qty, count in ((batch_a, 60, 2), (batch_b, 40, 1)):
        r = client.post(
            "/api/cutting/records",
            json={
                "work_order_id": cutting_wo["id"],
                "production_batch_id": batch["id"],
                "fabric_batch_id": None,
                "input_quantity": 20.0,
                "input_unit": "kg",
                "cut_pieces": qty,
                "passed_pieces": qty,
                "defective_pieces": 0,
                "waste_quantity": 0,
                "waste_unit": "kg",
                "bundles": [
                    {"color": "white", "size": "M", "quantity": qty // count, "count": count},
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        bundles.extend(r.json()["bundles"])

    _issue_required_accessories(client, auth_headers, po_id)
    for bundle in bundles:
        r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
        assert r.status_code == 200, r.text

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&only_received_sewing=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = [row for row in r.json() if int(row["production_order_id"]) == po_id]
    by_batch = {int(row["assignment_batch_id"]): row for row in rows}
    assert set(by_batch) == {int(batch_a["id"]), int(batch_b["id"])}
    assert int(by_batch[int(batch_a["id"])]["received_bundle_qty"]) == 60
    assert int(by_batch[int(batch_a["id"])]["planned_output_qty"]) == 60
    assert int(by_batch[int(batch_b["id"])]["assignable_qty"]) == 40

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = int(r.json()[0]["id"])

    assignment_ids = []
    for batch, qty in ((batch_a, 60), (batch_b, 40)):
        r = client.post(
            f"/api/work-orders/{sewing_wo['id']}/assignments",
            json={
                "work_order_id": sewing_wo["id"],
                "production_batch_id": batch["id"],
                "sewing_flow_id": flow_id,
                "quantity": qty,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert int(body["production_batch_id"]) == int(batch["id"])
        assignment_ids.append(int(body["id"]))

    r = client.get(f"/api/sewing-flows/{flow_id}/work-orders?only_active=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    active_rows = [row for row in r.json() if int(row.get("sewing_assignment_id") or 0) in assignment_ids]
    assert {int(row["production_batch_id"]) for row in active_rows} == {int(batch_a["id"]), int(batch_b["id"])}
    assert {int(row["planned_output_qty"]) for row in active_rows} == {40, 60}

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 10,
            "sewn_qty": 10,
            "passed_qty": 10,
            "failed_qty": 0,
            "sewing_assignment_id": assignment_ids[0],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    record_id = r.json()["id"]

    r = client.get(f"/api/sewing/records/{record_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["production_batch_id"]) == int(batch_a["id"])

    r = client.get(
        f"/api/sewing-daily-reports/line-context?sewing_flow_id={flow_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    context_row = next(row for row in r.json()["active_work_orders"] if int(row.get("sewing_assignment_id") or 0) == assignment_ids[0])
    assert int(context_row["production_batch_id"]) == int(batch_a["id"])


def test_sewing_flow_active_work_order_includes_model_number_and_fabric_picture(client, auth_headers):
    suffix = uuid4().hex[:10].upper()
    model_no = f"FLOW-{suffix}"
    fabric_image_url = f"https://example.com/flow-fabric-{suffix}.png"
    model = client.post(
        "/api/models",
        json={
            "code": f"{model_no}-V1",
            "name": "Sewing flow display model",
            "category": "Robe",
            "details_json": {"general": {"model_no": model_no, "variant_no": "V1"}},
            "status": "approved",
        },
        headers=auth_headers,
    )
    assert model.status_code == 201, model.text
    model_id = int(model.json()["id"])

    item = client.post(
        "/api/inventory/items",
        json={
            "sku": f"FLOW-FAB-{suffix}",
            "name": "Sewing flow fabric",
            "category": "fabric",
            "unit": "kg",
            "default_cost": 1,
            "reorder_level": 0,
            "track_batch": True,
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert item.status_code == 201, item.text
    bom = client.post(
        f"/api/models/{model_id}/bom",
        json={
            "item_id": int(item.json()["id"]),
            "photo_url": fabric_image_url,
            "quantity_per_piece": 1,
            "unit": "kg",
            "waste_percent": 0,
        },
        headers=auth_headers,
    )
    assert bom.status_code == 201, bom.text

    production = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 12,
            "items": [{"model_id": model_id, "color": "white", "size": "M", "planned_quantity": 12}],
        },
        headers=auth_headers,
    )
    assert production.status_code == 201, production.text
    po_id = int(production.json()["id"])
    work_orders = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    sewing_wo = next(row for row in work_orders.json() if row["operation"] == "sewing")

    flow = client.post(
        "/api/sewing-flows",
        json={"name": f"Flow {suffix}", "code": f"FLOW-{suffix}", "capacity_per_day": 20, "is_active": True},
        headers=auth_headers,
    )
    assert flow.status_code == 201, flow.text
    flow_id = int(flow.json()["id"])
    assignment = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={"work_order_id": sewing_wo["id"], "sewing_flow_id": flow_id, "quantity": 12},
        headers=auth_headers,
    )
    assert assignment.status_code == 201, assignment.text

    response = client.get(f"/api/sewing-flows/{flow_id}/work-orders?only_active=true", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if int(item["id"]) == int(sewing_wo["id"]))
    assert row["model_no"] == model_no
    assert row["material_image_url"] == fabric_image_url


def test_order_level_sewing_assignment_hides_received_batch_from_assignable_list(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 60,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60}],
            "batches": [{"name": "Batch 1", "planned_quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch = po["batches"][0]
    cutting_wo = next(w for w in po["work_orders"] if w["operation"] == "cutting")
    sewing_wo = next(w for w in po["work_orders"] if w["operation"] == "sewing")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 10.0,
            "input_unit": "kg",
            "cut_pieces": 60,
            "passed_pieces": 60,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [{"color": "white", "size": "M", "quantity": 60, "count": 1}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundle = r.json()["bundles"][0]

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/sewing-flows", headers=auth_headers)
    assert r.status_code == 200, r.text
    flow_id = int(r.json()[0]["id"])

    r = client.post(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        json={
            "work_order_id": sewing_wo["id"],
            "sewing_flow_id": flow_id,
            "quantity": 60,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["production_batch_id"] is None

    r = client.get(
        "/api/work-orders?operation=sewing&only_active=true&only_received_sewing=true",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = [row for row in r.json() if int(row["production_order_id"]) == po_id]
    assert rows == []


def test_cutting_uses_bundle_total_when_passed_pieces_are_lower(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
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
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    record_id = r.json()["id"]

    r = client.get(f"/api/cutting/records/{record_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert int(body["cut_pieces"]) == 600
    assert int(body["passed_pieces"]) == 600
    assert int(body["total_bundled_quantity"]) == 600

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    by_op = {w["operation"]: w for w in po["work_orders"]}
    assert by_op["cutting"]["status"] == "completed"
    assert int(by_op["cutting"]["passed_qty"]) == 600
    assert int(by_op["sewing"]["planned_output_qty"]) == 600


def test_cutting_can_complete_with_actual_quantity_below_plan(client, auth_headers):
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
                {"name": "Actual cutting batch", "planned_quantity": 444},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])
    _issue_required_accessories(client, auth_headers, po_id)

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch_id = int(po["batches"][0]["id"])
    by_op = {row["operation"]: row for row in po["work_orders"]}
    cutting_wo = by_op["cutting"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch_id,
            "fabric_batch_id": None,
            "input_quantity": 90,
            "input_unit": "kg",
            "cut_pieces": 444,
            "passed_pieces": 444,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 74, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{cutting_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"
    assert int(r.json()["passed_qty"]) == 444

    r = client.post(
        f"/api/work-orders/{cutting_wo['id']}/complete-cutting-shortage",
        json={},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    completed = r.json()
    assert completed["status"] == "completed"
    assert int(completed["planned_output_qty"]) == 600
    assert int(completed["actual_output_qty"]) == 444
    assert int(completed["passed_qty"]) == 444
    assert int(completed["failed_qty"]) == 156

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    refreshed = {row["operation"]: row for row in r.json()["work_orders"]}
    assert refreshed["cutting"]["status"] == "completed"
    assert refreshed["sewing"]["status"] == "in_progress"
    assert int(refreshed["sewing"]["planned_output_qty"]) == 600


def test_cutting_can_increase_bundle_quantity_before_bundles_leave_cutting(client, auth_headers):
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
    cutting_wo = next(w for w in po["work_orders"] if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 700,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    record_id = created["id"]
    bundle_id = created["bundles"][0]["id"]

    r = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": bundle_id, "quantity": 150}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["total_bundled_quantity"]) == 650
    assert int(r.json()["passed_pieces"]) == 650
    assert int(r.json()["cut_pieces"]) == 700

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["actual_bundle_quantity"]) == 650
    assert int(po["batches"][0]["planned_quantity"]) == 650
    by_op = {w["operation"]: w for w in po["work_orders"]}
    assert by_op["cutting"]["status"] == "completed"
    assert int(by_op["cutting"]["actual_input_qty"]) == 700
    assert int(by_op["cutting"]["actual_output_qty"]) == 650
    for op in ("sewing", "packaging", "storage_transfer"):
        assert int(by_op[op]["planned_output_qty"]) == 650


def test_cutting_bundle_quantity_adjustment_has_no_movement_block(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
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
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6, "next": "printing"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    record_id = created["id"]
    bundle_id = created["bundles"][0]["id"]

    r = client.post(f"/api/bundles/{bundle_id}/send-printing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": bundle_id, "quantity": 150}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["total_bundled_quantity"]) == 650

    r = client.post(f"/api/bundles/{bundle_id}/receive-printing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": bundle_id, "quantity": 160}]},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert int(r.json()["total_bundled_quantity"]) == 660


def test_cutting_can_add_extra_batch_and_record_bundles(client, auth_headers):
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
    first_batch = po["batches"][0]
    cutting_wo = next(w for w in po["work_orders"] if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": first_batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 120.0,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        f"/api/work-orders/{cutting_wo['id']}/extra-batch",
        json={"name": "Extra cut", "planned_quantity": 120},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    extra_batch = r.json()
    assert int(extra_batch["planned_quantity"]) == 120
    assert int(extra_batch["batch_index"]) == 2

    r = client.get(f"/api/work-orders/{cutting_wo['id']}/cutting-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress_rows = r.json()["items"]
    assert len(progress_rows) == 2
    assert int(progress_rows[1]["remaining_quantity"]) == 120

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": extra_batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 24.0,
            "input_unit": "kg",
            "cut_pieces": 120,
            "passed_pieces": 120,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 60, "count": 2},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()["bundles"]
    assert len(created) == 2
    assert {int(row["production_batch_id"]) for row in created} == {int(extra_batch["id"])}

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert len(po["batches"]) == 2
    assert int(po["actual_bundle_quantity"]) == 720
    by_op = {w["operation"]: w for w in po["work_orders"]}
    assert int(by_op["cutting"]["actual_output_qty"]) == 720
    for op in ("sewing", "packaging", "storage_transfer"):
        assert int(by_op[op]["planned_output_qty"]) == 720


def test_cutting_inventory_keeps_bundles_until_destination_receives(client, auth_headers):
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
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(row for row in r.json() if row["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 50,
            "input_unit": "kg",
            "cut_pieces": 50,
            "passed_pieces": 50,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 20, "count": 1, "next": "printing"},
                {"color": "white", "size": "M", "quantity": 30, "count": 1},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    printing_bundle, sewing_bundle = r.json()["bundles"]

    r = client.get("/api/bundles/cutting-inventory?page_size=2000", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert all("material_image_url" in row for row in r.json()["rows"])
    inventory_ids = {int(row["id"]) for row in r.json()["rows"]}
    assert int(printing_bundle["id"]) in inventory_ids
    assert int(sewing_bundle["id"]) in inventory_ids

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.post(f"/api/bundles/{sewing_bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/bundles/cutting-inventory?page_size=2000", headers=auth_headers)
    assert r.status_code == 200, r.text
    inventory_ids = {int(row["id"]) for row in r.json()["rows"]}
    assert int(printing_bundle["id"]) in inventory_ids
    assert int(sewing_bundle["id"]) not in inventory_ids

    r = client.post(f"/api/bundles/{printing_bundle['id']}/send-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_to_printing"

    r = client.get("/api/bundles/cutting-inventory?page_size=2000", headers=auth_headers)
    assert r.status_code == 200, r.text
    inventory_ids = {int(row["id"]) for row in r.json()["rows"]}
    assert int(printing_bundle["id"]) in inventory_ids

    r = client.post(f"/api/bundles/{printing_bundle['id']}/receive-printing", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/bundles/cutting-inventory?page_size=2000", headers=auth_headers)
    assert r.status_code == 200, r.text
    inventory_ids = {int(row["id"]) for row in r.json()["rows"]}
    assert int(printing_bundle["id"]) not in inventory_ids


def test_manual_sewing_receive_by_order_model_removes_bundle_inventory(client, auth_headers):
    bundle = _create_bundle_for_scan(client, auth_headers)
    po_id = int(bundle["production_order_id"])
    model_id = int(bundle["model_id"])
    _issue_required_accessories(client, auth_headers, po_id)

    r = client.get("/api/bundles/sewing-receive-options", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert all("material_image_url" in row for row in r.json())
    option = next(
        row
        for row in r.json()
        if int(row["production_order_id"]) == po_id and int(row["model_id"]) == model_id
    )
    assert int(option["bundle_count"]) == 1
    assert int(option["quantity"]) == int(bundle["quantity"])

    r = client.post(
        "/api/bundles/manual-receive-sewing",
        json={"production_order_id": po_id, "model_id": model_id},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert int(body["received_count"]) == 1
    assert int(body["received_quantity"]) == int(bundle["quantity"])
    assert int(bundle["id"]) in {int(bundle_id) for bundle_id in body["bundle_ids"]}

    r = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_sewing"

    r = client.get("/api/bundles/cutting-inventory?page_size=2000", headers=auth_headers)
    assert r.status_code == 200, r.text
    inventory_ids = {int(row["id"]) for row in r.json()["rows"]}
    assert int(bundle["id"]) not in inventory_ids


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
            "layer_material_kg": 2.5,
            "beika_kg": 1.25,
            "material_rolls_used": 3,
            "layup_operator_name": "Dilnoza Opa",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 50, "count": 1},
                {"color": "white", "size": "L", "quantity": 50, "count": 1},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    cutting_record_id = int(r.json()["id"])
    bundles = r.json()["bundles"]
    assert len(bundles) == 2
    r = client.get(f"/api/cutting/records/{cutting_record_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_record = r.json()
    assert float(cutting_record["layer_material_kg"]) == 2.5
    assert float(cutting_record["beika_kg"]) == 1.25
    assert float(cutting_record["material_rolls_used"]) == 3.0
    assert cutting_record["layup_operator_name"] == "Dilnoza Opa"

    r = client.get(f"/api/production-orders/{po['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po_detail = r.json()
    assert int(po_detail["planned_quantity"]) == 100
    assert int(po_detail["actual_bundle_quantity"]) == 100
    assert int(po_detail["actual_bundle_count"]) == 2

    _issue_required_accessories(client, auth_headers, int(po["id"]))
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
                {"model_id": 1, "color": "white", "size": "M", "quantity": 40},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "available packed quantity" in r.text

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
    assert any(b["id"] == milana_bundle["id"] and b["textile_code"] == "MIL" for b in r.json()["incoming_bundles"])

    r = client.get("/api/inbox?dept=BST", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(b["id"] == besttex_bundle["id"] for b in r.json()["incoming_bundles"])
    assert any(b["id"] == besttex_bundle["id"] and b["textile_code"] == "BST" for b in r.json()["incoming_bundles"])

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(row["production_order_id"] == po_id and row["textile_code"] == "MIXED" for row in body["incoming_work_orders"])

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.post(f"/api/bundles/{besttex_bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_sewing"
    assert r.json()["current_department_id"] == dept_by_code["BST"]["id"]

    r = client.post(f"/api/bundles/{milana_bundle['id']}/send-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_to_sewing"
    assert r.json()["next_department_id"] == dept_by_code["MIL"]["id"]
    assert r.json()["current_department_id"] == dept_by_code["MIL"]["id"]


def test_milana_sewing_inbox_includes_default_textile_work(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 80,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 80}],
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
            "input_quantity": 100.0,
            "input_unit": "kg",
            "cut_pieces": 80,
            "passed_pieces": 80,
            "defective_pieces": 0,
            "waste_quantity": 2.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 80, "count": 1, "next": "sewing"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundle = r.json()["bundles"][0]
    assert bundle["sewing_factory_code"] == "MIL"

    r = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["next_department_id"] == dept_by_code["MIL"]["id"]

    r = client.get("/api/inbox?dept=MIL", headers=auth_headers)
    assert r.status_code == 200, r.text
    milana_body = r.json()
    assert any(row["production_order_id"] == po_id and row["textile_code"] == "MIL" for row in milana_body["incoming_work_orders"])

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_body = r.json()
    assert any(row["production_order_id"] == po_id and row["textile_code"] == "MIL" for row in sewing_body["incoming_work_orders"])

    r = client.get("/api/inbox?dept=BST", headers=auth_headers)
    assert r.status_code == 200, r.text
    besttex_body = r.json()
    assert not any(row["production_order_id"] == po_id for row in besttex_body["incoming_work_orders"])


def test_sewing_inbox_hides_cancelled_production_order_bundles(client, auth_headers):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 80,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 80}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(w for w in r.json() if w["operation"] == "cutting")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 100.0,
            "input_unit": "kg",
            "cut_pieces": 80,
            "passed_pieces": 80,
            "defective_pieces": 0,
            "waste_quantity": 2.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 80, "count": 1, "next": "sewing"},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(row["production_order_id"] == po_id for row in body["incoming_work_orders"])
    assert any(row["production_order_id"] == po_id for row in body["incoming_bundle_groups"])

    from app.db.session import SessionLocal
    from app.models import ProductionOrder

    db = SessionLocal()
    try:
        po = db.get(ProductionOrder, po_id)
        po.status = "cancelled"
        db.commit()
    finally:
        db.close()

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("incoming_bundles", "incoming_bundle_groups", "incoming_work_orders", "pending_work_orders"):
        assert not any(row["production_order_id"] == po_id for row in body[key])


def test_branded_stock_routes_selected_cutting_department_to_ect(client, auth_headers):
    response = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 100,
            "cutting_department_code": "ECT",
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100},
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    production_order_id = int(response.json()["id"])

    departments = client.get("/api/departments", headers=auth_headers)
    assert departments.status_code == 200, departments.text
    department_by_code = {row["code"]: row for row in departments.json()}

    work_orders = client.get(
        f"/api/work-orders?production_order_id={production_order_id}",
        headers=auth_headers,
    )
    assert work_orders.status_code == 200, work_orders.text
    cutting_work_order = next(
        row for row in work_orders.json() if row["operation"] == "cutting"
    )
    assert cutting_work_order["department_id"] == department_by_code["ECT"]["id"]

    from app.core.security import create_access_token

    eco_headers = {
        "Authorization": f"Bearer {create_access_token(1, extra={'factory_code': 'ECO'})}",
    }
    ect_inbox = client.get("/api/inbox?dept=ECT", headers=eco_headers)
    assert ect_inbox.status_code == 200, ect_inbox.text
    assert any(
        row["production_order_id"] == production_order_id
        for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders")
        for row in ect_inbox.json()[key]
    )

    milana_cutting_inbox = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert milana_cutting_inbox.status_code == 200, milana_cutting_inbox.text
    assert not any(
        row["production_order_id"] == production_order_id
        for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders")
        for row in milana_cutting_inbox.json()[key]
    )


@pytest.mark.parametrize(
    ("factory_name", "cutting_code", "sewing_code", "packaging_code"),
    [
        ("besttex", "CUT", "BST", "BPK"),
        ("eco_cotton", "ECT", "ECO", "ECP"),
    ],
)
def test_external_textile_route_uses_factory_packaging_then_milana_storage(
    client,
    auth_headers,
    factory_name,
    cutting_code,
    sewing_code,
    packaging_code,
):
    so_id = _create_client_sales_order(client, auth_headers)
    _prepare_sales_order_for_po(client, auth_headers, so_id)

    r = client.post(
        "/api/planning/create-production-order",
        json={
            "production_type": "client_order",
            "sales_order_id": so_id,
            "model_id": 1,
            "planned_quantity": 100,
            "cutting_department_code": cutting_code,
            "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_data = r.json()
    po_id = po_data["id"]
    production_no = po_data["production_no"]

    r = client.get("/api/departments", headers=auth_headers)
    assert r.status_code == 200, r.text
    dept_by_code = {d["code"]: d for d in r.json()}
    assert sewing_code in dept_by_code
    assert packaging_code in dept_by_code
    assert cutting_code in dept_by_code
    assert "FGS" in dept_by_code

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_op = {w["operation"]: w for w in r.json()}
    assert by_op["cutting"]["department_id"] == dept_by_code[cutting_code]["id"]

    r = client.get(f"/api/inbox?dept={cutting_code}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(
        row["production_order_id"] == po_id
        for key in ("pending_work_orders", "in_progress_work_orders", "active_work_orders")
        for row in r.json()[key]
    )

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": by_op["cutting"]["id"],
            "fabric_batch_id": None,
            "input_quantity": 140.0,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 5.0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 1, "next": "sewing", "sewing_factory": factory_name},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    bundle = r.json()["bundles"][0]
    assert bundle["sewing_factory_code"] == sewing_code

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    routed = {w["operation"]: w for w in r.json()}
    sewing_wo = routed["sewing"]
    packaging_wo = routed["packaging"]
    assert sewing_wo["department_id"] == dept_by_code[sewing_code]["id"]
    assert packaging_wo["department_id"] == dept_by_code[packaging_code]["id"]
    assert routed["storage_transfer"]["department_id"] == dept_by_code["FGS"]["id"]

    r = client.get(
        f"/api/process-tracking?include_total=true&page_size=10&q={production_no}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    tracked = next(row for row in r.json()["rows"] if row["production_order_id"] == po_id)
    assert tracked["cutting_factories"] == [
        {"code": cutting_code, "name": dept_by_code[cutting_code]["name"]}
    ]
    assert tracked["sewing_factories"] == [
        {"code": sewing_code, "name": dept_by_code[sewing_code]["name"]}
    ]

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_body = r.json()
    assert any(row["production_order_id"] == po_id and row["textile_code"] == sewing_code for row in sewing_body["incoming_work_orders"])

    r = client.get(f"/api/inbox?dept={sewing_code}", headers=auth_headers)
    assert r.status_code == 200, r.text
    besttex_body = r.json()
    assert any(row["production_order_id"] == po_id and row["textile_code"] == sewing_code for row in besttex_body["incoming_work_orders"])

    r = client.get("/api/inbox?dept=MIL", headers=auth_headers)
    assert r.status_code == 200, r.text
    milana_body = r.json()
    assert not any(row["production_order_id"] == po_id for row in milana_body["incoming_work_orders"])

    r = client.get(f"/api/inbox?dept={packaging_code}", headers=auth_headers)
    assert r.status_code == 200, r.text
    bpk_expected = [
        row for row in r.json()["incoming_work_orders"]
        if int(row["production_order_id"]) == int(po_id)
    ]
    assert bpk_expected
    assert int(bpk_expected[0]["expected_qty"]) == 100

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.post(f"/api/bundles/{bundle['id']}/receive-sewing", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["current_department_id"] == dept_by_code[sewing_code]["id"]

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "input_qty": 0,
            "sewn_qty": 100,
            "passed_qty": 100,
            "failed_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/inbox?dept={packaging_code}", headers=auth_headers)
    assert r.status_code == 200, r.text
    bpk_ready = [
        row for row in r.json()["incoming_work_orders"]
        if int(row["production_order_id"]) == int(po_id)
    ]
    assert bpk_ready
    assert int(bpk_ready[0]["ready_qty"]) == 100

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "input_qty": 100,
            "packed_qty": 100,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "sales_order_id": so_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 100,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    package_id = r.json()["id"]

    r = client.get("/api/inbox?dept=FGS", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert any(p["id"] == package_id for p in r.json()["pending_packages"])

    r = client.post(f"/api/packages/{package_id}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_in_storage"


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

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    routed = {w["operation"]: w for w in r.json()}
    assert routed["sewing"]["department_id"] == dept_by_code["BST"]["id"]
    assert routed["packaging"]["department_id"] == dept_by_code["BPK"]["id"]

    r = client.get(f"/api/bundles/{bundle['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["next_department_id"] == dept_by_code["PRT"]["id"]

    r = client.post(f"/api/bundles/{bundle['id']}/send-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/bundles/{bundle['id']}/receive-printing", headers=auth_headers)
    assert r.status_code == 200, r.text
    _issue_required_accessories(client, auth_headers, po_id)
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
        assert int(refreshed[op]["planned_input_qty"]) == 108
        assert int(refreshed[op]["planned_output_qty"]) == 108

    _issue_required_accessories(client, auth_headers, po_id)
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
    assert int(r.json()["planned_output_qty"]) == 108


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
    assert [factory["code"] for factory in proc["cutting_factories"]] == ["CUT"]
    assert [factory["code"] for factory in proc["sewing_factories"]] == ["MIL"]
    assert len(proc["batches"]) == 2
    assert sorted(int(b["planned_quantity"]) for b in proc["batches"]) == [40, 60]
    assert int(proc["actual_quantity"]) == 0
    assert all(int(b["actual_quantity"]) == 0 for b in proc["batches"])
    assert all(str(b.get("batch_no", "")).replace("-", "").isdigit() for b in proc["batches"])


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
    assert int(proc["actual_quantity"]) == 60

    batch_a_proc = next(b for b in proc["batches"] if b["id"] == batch_a["id"])
    batch_a_cutting = next(s for s in batch_a_proc["stages"] if s["operation"] == "cutting")
    assert int(batch_a_cutting["planned"]) == 60
    assert int(batch_a_cutting["completed"]) == 60
    assert int(batch_a_proc["actual_quantity"]) == 60
    assert float(batch_a_cutting["progress_pct"]) == 100.0
    assert batch_a_cutting["status"] == "completed"

    batch_b_proc = next(b for b in proc["batches"] if b["id"] == batch_b["id"])
    batch_b_cutting = next(s for s in batch_b_proc["stages"] if s["operation"] == "cutting")
    assert int(batch_b_cutting["planned"]) == 40
    assert int(batch_b_cutting["completed"]) == 0
    assert int(batch_b_proc["actual_quantity"]) == 0
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


def test_partial_package_can_be_received_in_storage(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 58,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 58},
            ],
        },
        headers=auth_headers,
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
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 58}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert int(pkg["total_quantity"]) == 58
    assert int(pkg["capacity"]) == 60

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_in_storage"
    assert int(r.json()["total_quantity"]) == 58

    r = client.get("/api/process-tracking", headers=auth_headers)
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json() if p["production_order_id"] == po_id)
    storage = next(s for s in proc["stages"] if s["operation"] == "storage_transfer")
    assert int(storage["completed"]) == 58


def test_process_tracking_prefers_storage_when_partial_order_reaches_storage(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po = r.json()
    po_id = po["id"]

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 600,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 598}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received_in_storage"

    r = client.get(
        f"/api/process-tracking?q={po['production_no']}&include_total=true&page_size=10",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json()["rows"] if p["production_order_id"] == po_id)
    assert proc["po_status"] == "storage_transfer"
    assert proc["current_stage"] == "storage_transfer"
    assert proc["current_stage_status"] == "in_progress"
    storage = next(s for s in proc["stages"] if s["operation"] == "storage_transfer")
    assert int(storage["completed"]) == 598
    assert float(storage["progress_pct"]) == 99.7


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
    assert all(str(b.get("batch_no", "")).replace("-", "").isdigit() for b in po["batches"])
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


def test_sewing_failure_stays_open_until_recut_and_resewn(client, auth_headers):
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

    _issue_required_accessories(client, auth_headers, po_id)
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
            "line_name": "Line 7",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/sewing-batch-progress", headers=auth_headers)
    assert r.status_code == 200, r.text
    progress = r.json()["items"][0]
    assert int(progress["passed_qty"]) == 599
    assert int(progress["failed_qty"]) == 1
    assert int(progress["remaining_quantity"]) == 1
    assert int(progress["waiting_replacement_qty"]) == 1
    assert float(progress["progress_pct"]) < 100.0

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/replacement-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    replacement = r.json()
    assert int(replacement["open_qty"]) == 1
    assert int(replacement["waiting_cutting_qty"]) == 1
    assert int(replacement["waiting_sewing_qty"]) == 0

    r = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert r.status_code == 200, r.text
    cutting_inbox = r.json()
    replacement_rows = cutting_inbox["replacement_cutting_work"]
    assert len(replacement_rows) == 1
    assert replacement_rows[0]["cutting_work_order_id"] == cutting_wo["id"]
    assert replacement_rows[0]["production_order_id"] == po_id
    assert int(replacement_rows[0]["remaining_qty"]) == 1
    assert replacement_rows[0]["sewing_line_name"] == "Line 7"
    assert cutting_wo["id"] not in {row["id"] for row in cutting_inbox["pending_work_orders"]}

    r = client.post(f"/api/work-orders/{sewing_wo['id']}/complete", headers=auth_headers)
    assert r.status_code == 409, r.text

    r = client.get(f"/api/work-orders/{cutting_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 1.0,
            "input_unit": "kg",
            "cut_pieces": 1,
            "passed_pieces": 1,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert int(r.json()["replacement_cut_qty"]) == 1

    r = client.get("/api/inbox?dept=CUT", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["replacement_cutting_work"] == []

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/replacement-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["waiting_cutting_qty"]) == 0
    assert int(r.json()["waiting_sewing_qty"]) == 1

    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_replacement_rows = [
        row for row in r.json()["replacement_sewing_work"]
        if int(row["production_order_id"]) == int(po_id)
    ]
    assert len(sewing_replacement_rows) == 1
    assert int(sewing_replacement_rows[0]["sewing_work_order_id"]) == int(sewing_wo["id"])
    assert int(sewing_replacement_rows[0]["remaining_qty"]) == 1

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 1,
            "sewn_qty": 1,
            "passed_qty": 1,
            "failed_qty": 0,
            "rework_qty": 0,
            "rejected_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert int(r.json()["replacement_completed_qty"]) == 1

    r = client.get(f"/api/work-orders/{sewing_wo['id']}/replacement-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["open_qty"]) == 0
    r = client.get("/api/inbox?dept=SEW", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert not any(
        int(row["production_order_id"]) == int(po_id)
        for row in r.json()["replacement_sewing_work"]
    )
    r = client.get(f"/api/work-orders/{sewing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


def test_packaging_progress_keeps_failed_sewing_quantity_open(client, auth_headers):
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

    _issue_required_accessories(client, auth_headers, po_id)
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
        "/api/packaging/receive-from-sewing",
        json={
            "work_order_id": packaging_wo["id"],
            "production_batch_id": batch["id"],
            "quantity": 599,
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
    assert int(progress["remaining_quantity"]) == 1
    assert int(progress["waiting_replacement_qty"]) == 1
    assert float(progress["progress_pct"]) < 100.0
    assert int(progress["available_to_package"]) == 599

    r = client.get("/api/packaging/received-orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    queue_row = next(row for row in r.json() if int(row["production_order_id"]) == po_id)
    assert int(queue_row["remaining_quantity"]) == 0
    assert int(queue_row["waiting_replacement_quantity"]) == 1


def test_process_tracking_keeps_failed_sewing_open_for_storage(client, auth_headers):
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
    storage_wo = by_op["storage_transfer"]

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

    _issue_required_accessories(client, auth_headers, po_id)
    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 600,
            "sewn_qty": 598,
            "passed_qty": 598,
            "failed_qty": 2,
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
            "input_qty": 598,
            "packed_qty": 598,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "production_batch_id": batch["id"],
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 600,
            "items": [{"model_id": 1, "color": "white", "size": "M", "quantity": 598}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg = r.json()

    r = client.post(f"/api/packages/{pkg['id']}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/work-orders/{storage_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    refreshed_storage = r.json()
    assert refreshed_storage["status"] == "in_progress"
    assert int(refreshed_storage["passed_qty"]) == 598
    assert int(refreshed_storage["failed_qty"]) == 0

    r = client.get(
        f"/api/process-tracking?q={po['production_no']}&include_total=true&page_size=10",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    proc = next(p for p in r.json()["rows"] if p["production_order_id"] == po_id)
    assert proc["current_stage"] == "storage_transfer"

    by_stage = {stage["operation"]: stage for stage in proc["stages"]}
    assert int(by_stage["sewing"]["completed"]) == 598
    assert int(by_stage["sewing"]["failed"]) == 2
    assert int(by_stage["sewing"]["processed"]) == 598
    assert float(by_stage["sewing"]["progress_pct"]) < 100.0
    assert by_stage["packaging"]["status"] == "in_progress"
    assert int(by_stage["packaging"]["completed"]) == 598
    assert int(by_stage["packaging"]["processed"]) == 598
    assert by_stage["storage_transfer"]["status"] == "in_progress"
    assert int(by_stage["storage_transfer"]["completed"]) == 598
    assert int(by_stage["storage_transfer"]["failed"]) == 0
    assert int(by_stage["storage_transfer"]["processed"]) == 598

    batch_proc = proc["batches"][0]
    batch_storage = next(stage for stage in batch_proc["stages"] if stage["operation"] == "storage_transfer")
    assert batch_proc["current_stage"] == "storage_transfer"
    assert int(batch_storage["completed"]) == 598
    assert int(batch_storage["processed"]) == 598


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
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": None,
            "input_quantity": 100.0,
            "input_unit": "kg",
            "cut_pieces": 1500,
            "passed_pieces": 1500,
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


def test_packaging_actual_quantity_tracks_sewing_handoff_and_allows_breakdown_edit(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 600,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 300},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 300},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    sewing_wo = next(w for w in r.json() if w["operation"] == "sewing")

    r = client.patch(
        f"/api/work-orders/{sewing_wo['id']}",
        json={"actual_input_qty": 620, "actual_output_qty": 620, "passed_qty": 620},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["planned_quantity"]) == 600
    assert int(po["actual_quantity"]) == 620
    item_m = next(i for i in po["items"] if i["size"] == "M")
    item_l = next(i for i in po["items"] if i["size"] == "L")

    r = client.put(
        f"/api/production-orders/{po_id}/breakdown",
        json={
            "items": [
                {"id": item_m["id"], "color": "white", "size": "M", "planned_quantity": 310},
                {"id": item_l["id"], "color": "white", "size": "L", "planned_quantity": 310},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    po = r.json()
    assert int(po["actual_quantity"]) == 620
    assert sorted((i["size"], int(i["planned_quantity"])) for i in po["items"]) == [("L", 310), ("M", 310)]


def test_packaging_can_create_sticker_without_sewing_total(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 462,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 462},
            ],
            "batches": [
                {"name": "Batch 1", "planned_quantity": 462},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch = po["batches"][0]
    by_operation = {row["operation"]: row for row in po["work_orders"]}
    sewing_wo = by_operation["sewing"]
    packaging_wo = by_operation["packaging"]
    assert int(sewing_wo["passed_qty"]) == 0

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 420,
            "packed_qty": 420,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packaging/records",
        json={
            "work_order_id": packaging_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 43,
            "packed_qty": 43,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "packaging batch plan 462" in r.text

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "production_batch_id": batch["id"],
            "model_id": 1,
            "color": "white",
            "package_type": "bag",
            "capacity": 60,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    package_id = int(r.json()["id"])

    r = client.get(f"/api/packages/{package_id}/label", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "Package Label" in r.text

    r = client.get(f"/api/work-orders/{sewing_wo['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json()["passed_qty"]) == 0


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

    _issue_required_accessories(client, auth_headers, po_id)
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
            "input_qty": 61,
            "packed_qty": 61,
            "damaged_qty": 0,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "packaging batch plan 60" in r.text

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


def test_sewing_records_partial_output_by_size_and_tracks_remaining(client, auth_headers):
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 100,
            "items": [
                {"model_id": 1, "color": "white", "size": "M", "planned_quantity": 60},
                {"model_id": 1, "color": "white", "size": "L", "planned_quantity": 40},
            ],
            "batches": [{"name": "Batch 1", "planned_quantity": 100}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    work_orders = {row["operation"]: row for row in po["work_orders"]}
    batch_id = po["batches"][0]["id"]
    cutting_wo = work_orders["cutting"]
    sewing_wo = work_orders["sewing"]

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch_id,
            "fabric_batch_id": None,
            "input_quantity": 20,
            "input_unit": "kg",
            "cut_pieces": 100,
            "passed_pieces": 100,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [
                {"color": "white", "size": "M", "quantity": 60, "count": 1},
                {"color": "white", "size": "L", "quantity": 40, "count": 1},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    _issue_required_accessories(client, auth_headers, po_id)

    r = client.get(
        f"/api/work-orders/{sewing_wo['id']}/sewing-size-progress?production_batch_id={batch_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    initial = {row["size"]: row for row in r.json()["items"]}
    assert initial["M"]["remaining_quantity"] == 60
    assert initial["L"]["remaining_quantity"] == 40

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch_id,
            "input_qty": 40,
            "sewn_qty": 40,
            "passed_qty": 40,
            "failed_qty": 0,
            "size_quantities": [{"size": "M", "quantity": 39}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "must equal the passed output quantity" in r.text

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch_id,
            "input_qty": 40,
            "sewn_qty": 40,
            "passed_qty": 40,
            "failed_qty": 0,
            "size_quantities": [
                {"size": "M", "quantity": 30},
                {"size": "L", "quantity": 10},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    record_id = r.json()["id"]

    r = client.get(f"/api/sewing/records/{record_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["size_quantities"] == [
        {"size": "M", "quantity": 30},
        {"size": "L", "quantity": 10},
    ]

    r = client.get(
        f"/api/work-orders/{sewing_wo['id']}/sewing-size-progress?production_batch_id={batch_id}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    progress = {row["size"]: row for row in r.json()["items"]}
    assert progress["M"]["completed_quantity"] == 30
    assert progress["M"]["remaining_quantity"] == 30
    assert progress["L"]["completed_quantity"] == 10
    assert progress["L"]["remaining_quantity"] == 30

    r = client.get(
        f"/api/process-tracking?sewing_completed_only=true&include_total=true&q={po['production_no']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 0
    assert r.json()["rows"] == []

    r = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch_id,
            "input_qty": 31,
            "sewn_qty": 31,
            "passed_qty": 31,
            "failed_qty": 0,
            "size_quantities": [{"size": "M", "quantity": 31}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 400, r.text
    assert "exceeds remaining 30" in r.text

    r = client.post(f"/api/work-orders/{sewing_wo['id']}/complete", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get(
        f"/api/process-tracking?sewing_completed_only=true&include_total=true&q={po['production_no']}",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["total"] == 1
    assert len(payload["rows"]) == 1
    tracked = payload["rows"][0]
    assert int(tracked["planned_quantity"]) == 100
    assert int(tracked["sewing_completed_quantity"]) == 40
    assert int(tracked["sewing_unallocated_quantity"]) == 0
    tracked_sizes = {row["size"]: row for row in tracked["sizes"]}
    assert int(tracked_sizes["M"]["sewing_completed_quantity"]) == 30
    assert int(tracked_sizes["L"]["sewing_completed_quantity"]) == 10
    assert len(tracked["batches"]) == 1
    assert int(tracked["batches"][0]["sewing_completed_quantity"]) == 40
    batch_sizes = {row["size"]: row for row in tracked["batches"][0]["sewing_sizes"]}
    assert int(batch_sizes["M"]["completed_quantity"]) == 30
    assert int(batch_sizes["M"]["sewing_completed_quantity"]) == 30
    assert int(batch_sizes["L"]["completed_quantity"]) == 10


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


def test_cutting_edits_after_sewing_start_reconcile_the_whole_workflow(client, auth_headers):
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
                {"name": "Editable batch", "planned_quantity": 600},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    po = r.json()
    batch = po["batches"][0]
    cutting_wo = next(row for row in po["work_orders"] if row["operation"] == "cutting")
    sewing_wo = next(row for row in po["work_orders"] if row["operation"] == "sewing")

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch["id"],
            "fabric_batch_id": None,
            "input_quantity": 120,
            "input_unit": "kg",
            "cut_pieces": 600,
            "passed_pieces": 600,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "layer_material_kg": 20,
            "bundles": [
                {"color": "white", "size": "M", "quantity": 100, "count": 6},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    record_id = int(created["id"])
    first_bundle_id = int(created["bundles"][0]["id"])

    _issue_required_accessories(client, auth_headers, po_id)
    flows = client.get("/api/sewing-flows", headers=auth_headers)
    assert flows.status_code == 200, flows.text
    flow_id = int(flows.json()[0]["id"])
    accepted = client.post(
        f"/api/bundles/sewing-batches/{batch['id']}/accept",
        json={"sewing_flow_id": flow_id},
        headers=auth_headers,
    )
    assert accepted.status_code == 200, accepted.text
    assignment_id = int(accepted.json()["sewing_assignment_id"])

    increased = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={
            "bundles": [
                {"id": first_bundle_id, "quantity": 150, "color": "ivory", "size": "L"},
            ],
        },
        headers=auth_headers,
    )
    assert increased.status_code == 200, increased.text
    assert int(increased.json()["total_bundled_quantity"]) == 650
    edited_bundle = next(row for row in increased.json()["bundles"] if int(row["id"]) == first_bundle_id)
    assert edited_bundle["color"] == "ivory"
    assert edited_bundle["size"] == "L"

    assignments = client.get(
        f"/api/work-orders/{sewing_wo['id']}/assignments",
        headers=auth_headers,
    )
    assert assignments.status_code == 200, assignments.text
    assignment = next(row for row in assignments.json() if int(row["id"]) == assignment_id)
    assert int(assignment["quantity"]) == 650

    lowered = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": first_bundle_id, "quantity": 120}]},
        headers=auth_headers,
    )
    assert lowered.status_code == 200, lowered.text
    assert int(lowered.json()["total_bundled_quantity"]) == 620

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    refreshed = r.json()
    assert int(refreshed["batches"][0]["planned_quantity"]) == 620
    by_operation = {row["operation"]: row for row in refreshed["work_orders"]}
    assert int(by_operation["cutting"]["planned_output_qty"]) == 650
    for operation in ("sewing", "packaging", "storage_transfer"):
        assert int(by_operation[operation]["planned_output_qty"]) == 620

    batch_update = client.patch(
        f"/api/work-orders/{cutting_wo['id']}/batches/{batch['id']}",
        json={
            "name": "Milana corrected batch",
            "planned_quantity": 700,
            "deadline": "2030-01-15T00:00:00Z",
            "notes": "Updated after sewing accepted the batch",
        },
        headers=auth_headers,
    )
    assert batch_update.status_code == 200, batch_update.text
    assert batch_update.json()["name"] == "Milana corrected batch"
    assert int(batch_update.json()["planned_quantity"]) == 700

    r = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    by_operation = {row["operation"]: row for row in r.json()["work_orders"]}
    for operation in ("cutting", "sewing", "packaging", "storage_transfer"):
        assert int(by_operation[operation]["planned_output_qty"]) == 700

    details = client.patch(
        f"/api/cutting/records/{record_id}",
        json={
            "layer_material_kg": 22.5,
            "beika_kg": 3.25,
            "material_rolls_used": 7,
            "layup_operator_name": "Updated Nastilchi",
            "notes": "Corrected while sewing is in progress",
        },
        headers=auth_headers,
    )
    assert details.status_code == 200, details.text
    assert float(details.json()["layer_material_kg"]) == 22.5
    assert float(details.json()["beika_kg"]) == 3.25
    assert details.json()["layup_operator_name"] == "Updated Nastilchi"

    sewn = client.post(
        "/api/sewing/records",
        json={
            "work_order_id": sewing_wo["id"],
            "production_batch_id": batch["id"],
            "input_qty": 610,
            "sewn_qty": 610,
            "passed_qty": 610,
            "failed_qty": 0,
            "sewing_assignment_id": assignment_id,
        },
        headers=auth_headers,
    )
    assert sewn.status_code == 201, sewn.text

    below_evidence = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": first_bundle_id, "quantity": 100}]},
        headers=auth_headers,
    )
    assert below_evidence.status_code == 409, below_evidence.text
    assert "downstream output (610)" in below_evidence.text

    batch_below_evidence = client.patch(
        f"/api/work-orders/{cutting_wo['id']}/batches/{batch['id']}",
        json={"planned_quantity": 600},
        headers=auth_headers,
    )
    assert batch_below_evidence.status_code == 409, batch_below_evidence.text
    assert "workflow evidence (620)" in batch_below_evidence.text

    identity_after_output = client.patch(
        f"/api/cutting/records/{record_id}/bundle-quantities",
        json={"bundles": [{"id": first_bundle_id, "quantity": 120, "color": "black"}]},
        headers=auth_headers,
    )
    assert identity_after_output.status_code == 409, identity_after_output.text
    assert "Color and size" in identity_after_output.text
