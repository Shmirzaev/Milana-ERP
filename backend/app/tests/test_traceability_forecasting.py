from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock,
    Item,
    ManualAccessoryIssue,
    ModelBOM,
    Package,
    ProductionOrder,
    ProductionOrderItem,
    SalesOrder,
    SalesOrderItem,
    StockMovement,
)


def _token_headers(client, email: str, password: str = "demo12345") -> dict[str, str]:
    r = client.post("/api/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _warehouse(client, headers, warehouse_type: str) -> dict:
    r = client.get("/api/inventory/warehouses", headers=headers)
    assert r.status_code == 200, r.text
    return next(row for row in r.json() if row["type"] == warehouse_type)


def _create_traceable_package(client, headers, *, with_cutting_batch: bool = True, receive_storage: bool = False) -> dict:
    suffix = uuid4().hex[:8]
    color = f"trace-{suffix}"
    size = "M"
    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 30,
            "items": [{"model_id": 1, "color": color, "size": size, "planned_quantity": 30}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.get(f"/api/work-orders?production_order_id={po_id}", headers=headers)
    assert r.status_code == 200, r.text
    cutting_wo = next(row for row in r.json() if row["operation"] == "cutting")

    fabric_batch_id = None
    if with_cutting_batch:
        warehouse = _warehouse(client, headers, "fabric_storage")
        r = client.post(
            "/api/inventory/receive",
            json={
                "item_id": 1,
                "batch_no": f"TR-FAB-{suffix}",
                "quantity": 25,
                "unit": "kg",
                "cost_per_unit": 3,
                "warehouse_id": warehouse["id"],
                "qc_status": "passed",
            },
            headers=headers,
        )
        assert r.status_code == 201, r.text
        fabric_batch_id = int(r.json()["id"])

    r = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "fabric_batch_id": fabric_batch_id,
            "input_quantity": 1,
            "input_unit": "kg",
            "cut_pieces": 30,
            "passed_pieces": 30,
            "defective_pieces": 0,
            "waste_quantity": 0.5,
            "waste_unit": "kg",
            "bundles": [{"color": color, "size": size, "quantity": 30, "count": 1}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": 1,
            "color": color,
            "capacity": 60,
            "items": [{"model_id": 1, "color": color, "size": size, "quantity": 30}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    package = r.json()
    if receive_storage:
        r = client.post(f"/api/packages/{package['id']}/receive-storage", headers=headers)
        assert r.status_code == 200, r.text
        package = r.json()
    return {"package": package, "production_order_id": po_id, "fabric_batch_id": fabric_batch_id}


def _insert_branded_history(*, color: str, size: str, quantities: list[int], available_qty: int) -> None:
    db = SessionLocal()
    try:
        for qty in quantities:
            so = SalesOrder(
                order_no=f"SO-FC-{uuid4().hex[:10]}",
                order_type="branded_stock_sale",
                status="ready",
                total_amount=qty * 10,
                created_at=datetime.now(timezone.utc),
            )
            db.add(so)
            db.flush()
            db.add(
                SalesOrderItem(
                    sales_order_id=so.id,
                    model_id=1,
                    color=color,
                    size=size,
                    quantity=qty,
                    unit_price=10,
                    source_type="produce_new",
                )
            )
        if available_qty > 0:
            db.add(
                FinishedGoodsStock(
                    model_id=1,
                    color=color,
                    size=size,
                    quantity=available_qty,
                    available_qty=available_qty,
                    reserved_qty=0,
                    sold_qty=0,
                    cost_per_piece=5,
                    selling_price=10,
                    status="available",
                )
            )
        db.commit()
    finally:
        db.close()


def _create_reorder_item(*, reorder_level: float, stock_qty: float = 0) -> tuple[int, str]:
    db = SessionLocal()
    try:
        suffix = uuid4().hex[:8].upper()
        item = Item(
            sku=f"FC-RE-{suffix}",
            name=f"Forecast reorder {suffix}",
            category="accessory",
            unit="pcs",
            default_cost=1,
            reorder_level=reorder_level,
            track_batch=False,
            is_active=True,
        )
        db.add(item)
        db.flush()
        if stock_qty:
            db.add(
                StockMovement(
                    movement_type="adjustment",
                    item_id=item.id,
                    quantity=stock_qty,
                    unit=item.unit,
                    reference_type="ForecastTest",
                )
            )
        db.commit()
        return int(item.id), item.sku
    finally:
        db.close()


def _insert_branded_production_history(
    *,
    color: str,
    size: str,
    quantities: list[int],
    status: str = "finished_storage",
    brand_id: int | None = None,
    available_qty: int = 0,
) -> list[int]:
    db = SessionLocal()
    try:
        production_order_ids: list[int] = []
        for qty in quantities:
            po = ProductionOrder(
                production_no=f"PO-FC-{uuid4().hex[:10]}",
                production_type="branded_stock",
                model_id=1,
                brand_id=brand_id,
                status=status,
                planned_quantity=qty,
                created_at=datetime.now(timezone.utc),
            )
            db.add(po)
            db.flush()
            production_order_ids.append(int(po.id))
            db.add(
                ProductionOrderItem(
                    production_order_id=po.id,
                    model_id=1,
                    color=color,
                    size=size,
                    planned_quantity=qty,
                )
            )
        if available_qty > 0:
            db.add(
                FinishedGoodsStock(
                    production_order_id=production_order_ids[-1],
                    model_id=1,
                    color=color,
                    size=size,
                    quantity=available_qty,
                    available_qty=available_qty,
                    reserved_qty=0,
                    sold_qty=0,
                    cost_per_piece=5,
                    selling_price=10,
                    status="available",
                )
            )
        db.commit()
        return production_order_ids
    finally:
        db.close()


def test_package_traceability_returns_package_items_and_scans(client, auth_headers):
    created = _create_traceable_package(client, auth_headers)
    pkg = created["package"]

    r = client.get(f"/api/traceability/package/{pkg['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["package"]["package_no"] == pkg["package_no"]
    assert body["package_items"]
    assert any(row["scan_type"] == "packed" for row in body["package_scan_history"])
    assert body["trace_gap"] is True


def test_traceability_includes_cutting_fabric_batch_when_linked(client, auth_headers):
    created = _create_traceable_package(client, auth_headers, with_cutting_batch=True)
    pkg = created["package"]

    r = client.get(f"/api/traceability/package/{pkg['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    batches = r.json()["material_batches"]
    assert any(int(row["id"]) == int(created["fabric_batch_id"]) for row in batches)


def test_production_batch_qr_traceability_is_strict_and_reports_live_progress(client, auth_headers):
    suffix = uuid4().hex[:8]
    production = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": 1,
            "planned_quantity": 30,
            "items": [{"model_id": 1, "color": f"batch-{suffix}", "size": "M", "planned_quantity": 30}],
            "batches": [{"name": "QR trace batch", "planned_quantity": 30}],
        },
        headers=auth_headers,
    )
    assert production.status_code == 201, production.text
    po_id = int(production.json()["id"])
    production_detail = client.get(f"/api/production-orders/{po_id}", headers=auth_headers)
    assert production_detail.status_code == 200, production_detail.text
    batch = production_detail.json()["batches"][0]
    batch_id = int(batch["id"])

    warehouse = _warehouse(client, auth_headers, "fabric_storage")
    received = client.post(
        "/api/inventory/receive",
        json={
            "item_id": 1,
            "batch_no": f"QR-FAB-{suffix}",
            "quantity": 10,
            "unit": "kg",
            "cost_per_unit": 3,
            "warehouse_id": warehouse["id"],
            "qc_status": "passed",
        },
        headers=auth_headers,
    )
    assert received.status_code == 201, received.text
    fabric_batch_id = int(received.json()["id"])

    work_orders = client.get(f"/api/work-orders?production_order_id={po_id}", headers=auth_headers)
    assert work_orders.status_code == 200, work_orders.text
    cutting_wo = next(row for row in work_orders.json() if row["operation"] == "cutting")
    cutting = client.post(
        "/api/cutting/records",
        json={
            "work_order_id": cutting_wo["id"],
            "production_batch_id": batch_id,
            "fabric_batch_id": fabric_batch_id,
            "input_quantity": 2.5,
            "input_unit": "kg",
            "cut_pieces": 30,
            "passed_pieces": 30,
            "defective_pieces": 0,
            "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [{"color": f"batch-{suffix}", "size": "M", "quantity": 30, "count": 1}],
        },
        headers=auth_headers,
    )
    assert cutting.status_code == 201, cutting.text

    db = SessionLocal()
    try:
        db.add(
            ManualAccessoryIssue(
                production_order_id=po_id,
                item_name="Test button",
                item_sku=f"BTN-{suffix}",
                quantity=12,
                unit="pcs",
                notes="Batch QR traceability test",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"/api/traceability/production-batch/{batch_id}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subject_type"] == "production_batch"
    assert int(body["production_batch"]["id"]) == batch_id
    assert int(body["quantity_summary"]["planned"]) == 30
    assert int(body["quantity_summary"]["cut_created"]) == 30
    assert int(body["quantity_summary"]["cut_usable"]) == 30
    assert body["current_process"]["operation"] == "sewing"
    assert body["current_process"]["status"] == "waiting"
    assert any(
        int(row["stock_batch_id"]) == fabric_batch_id and float(row["used_quantity"]) == 2.5
        for row in body["material_usage"]
        if row["stock_batch_id"] is not None
    )
    assert any(row["item_name"] == "Test button" and float(row["used_quantity"]) == 12 for row in body["accessory_usage"])
    assert body["accessory_scope"] == "production_order"
    assert all(int(row["production_batch_id"]) == batch_id for row in body["cutting_records"])
    assert all(int(row["production_batch_id"]) == batch_id for row in body["bundles"])

    compact = client.get(f"/api/traceability/production-batch/BATCH_ID:{batch_id}", headers=auth_headers)
    assert compact.status_code == 200, compact.text
    assert int(compact.json()["production_batch"]["id"]) == batch_id


def test_traceability_gaps_are_returned_when_links_missing(client, auth_headers):
    created = _create_traceable_package(client, auth_headers, with_cutting_batch=False)
    pkg = created["package"]

    r = client.get(f"/api/traceability/package/{pkg['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    gaps = r.json()["gaps"]
    assert "No fabric batch linked to cutting record" in gaps
    assert "Package has no warehouse receive scan" in gaps


def test_shipment_traceability_returns_shipment_packages(client, auth_headers):
    created = _create_traceable_package(client, auth_headers, receive_storage=True)
    pkg = created["package"]

    r = client.post("/api/shipments", json={"notes": "traceability test"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    shipment_id = int(r.json()["id"])
    r = client.post(f"/api/shipments/{shipment_id}/add-package?package_id={pkg['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get(f"/api/traceability/shipment/{shipment_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["shipment"]["id"] == shipment_id
    assert any(int(row["package_id"]) == int(pkg["id"]) for row in body["shipment_packages"])


def test_warehouse_exit_without_sales_order_requires_reference_scan_and_available_stock(client, auth_headers):
    created = _create_traceable_package(client, auth_headers, receive_storage=True)
    pkg = created["package"]
    package_id = int(pkg["id"])

    missing_reference = client.post("/api/shipments", json={}, headers=auth_headers)
    assert missing_reference.status_code == 400, missing_reference.text
    assert "reference is required" in missing_reference.text.lower()

    first = client.post(
        "/api/shipments",
        json={"notes": "Sample room issue approved by warehouse manager"},
        headers=auth_headers,
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    first_id = int(first_body["id"])
    assert first_body["sales_order_id"] is None
    assert first_body["shipment_type"] == "warehouse_exit"

    added = client.post(
        f"/api/shipments/{first_id}/add-package?package_id={package_id}",
        headers=auth_headers,
    )
    assert added.status_code == 200, added.text

    second = client.post(
        "/api/shipments",
        json={"notes": "Second manual exit"},
        headers=auth_headers,
    )
    assert second.status_code == 201, second.text
    second_id = int(second.json()["id"])
    duplicate_scan = client.post(
        f"/api/shipments/{second_id}/scan-package",
        json={"code": pkg["barcode"]},
        headers=auth_headers,
    )
    assert duplicate_scan.status_code == 200, duplicate_scan.text
    assert duplicate_scan.json()["ok"] is False
    assert "already attached" in duplicate_scan.json()["message"].lower()

    unscanned_ship = client.post(f"/api/shipments/{first_id}/mark-shipped", headers=auth_headers)
    assert unscanned_ship.status_code == 409, unscanned_ship.text
    assert "scan all shipment packages" in unscanned_ship.text.lower()

    premature_delivery = client.post(f"/api/shipments/{first_id}/deliver", headers=auth_headers)
    assert premature_delivery.status_code == 409, premature_delivery.text

    scanned = client.post(
        f"/api/shipments/{first_id}/scan-package",
        json={"code": pkg["barcode"]},
        headers=auth_headers,
    )
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["ok"] is True
    assert scanned.json()["is_complete"] is True

    shipped = client.post(f"/api/shipments/{first_id}/mark-shipped", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    assert shipped.json()["status"] == "shipped"

    db = SessionLocal()
    try:
        package = db.get(Package, package_id)
        stock_rows = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).all()
        assert package is not None and package.status == "shipped"
        assert stock_rows
        assert sum(int(row.available_qty or 0) for row in stock_rows) == 0
        assert sum(int(row.sold_qty or 0) for row in stock_rows) == sum(int(row.quantity or 0) for row in stock_rows)
    finally:
        db.close()

    delivered = client.post(f"/api/shipments/{first_id}/deliver", headers=auth_headers)
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "delivered"


def test_traceability_export_returns_html(client, auth_headers):
    created = _create_traceable_package(client, auth_headers)
    pkg = created["package"]

    r = client.get(f"/api/traceability/export/package/{pkg['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    assert "Product Passport" in r.text


def test_traceability_permission_denied(client, auth_headers):
    created = _create_traceable_package(client, auth_headers)
    finance_headers = _token_headers(client, "finance@example.com")

    r = client.get(f"/api/traceability/package/{created['package']['id']}", headers=finance_headers)
    assert r.status_code == 403, r.text
    r = client.get("/api/traceability/production-batch/1", headers=finance_headers)
    assert r.status_code == 403, r.text


def test_forecasting_branded_stock_suggestions_from_history(client, auth_headers):
    color = f"forecast-{uuid4().hex[:8]}"
    size = "S"
    _insert_branded_history(color=color, size=size, quantities=[20, 20], available_qty=0)

    r = client.get("/api/forecasting/branded-stock-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((item for item in r.json() if item["color"] == color and item["size"] == size), None)
    assert row is not None
    assert int(row["suggested_quantity"]) > 0
    assert row["confidence"] in {"low", "medium", "high"}
    assert "Projected" in row["reason"]


def test_forecasting_no_suggestion_when_finished_goods_stock_is_enough(client, auth_headers):
    color = f"forecast-enough-{uuid4().hex[:8]}"
    size = "L"
    _insert_branded_history(color=color, size=size, quantities=[5], available_qty=100)

    r = client.get("/api/forecasting/branded-stock-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert not any(item["color"] == color and item["size"] == size for item in r.json())


def test_forecasting_uses_branded_production_history_when_variant_has_no_sales(client, auth_headers):
    color = f"forecast-production-{uuid4().hex[:8]}"
    size = "XL"
    _insert_branded_production_history(color=color, size=size, quantities=[20, 20])

    r = client.get("/api/forecasting/branded-stock-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((item for item in r.json() if item["color"] == color and item["size"] == size), None)
    assert row is not None
    assert row["demand_source"] == "branded_production_orders"
    assert int(row["suggested_quantity"]) > 0

    dashboard = client.get("/api/forecasting/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200, dashboard.text
    assert int(dashboard.json()["cards"]["demand_trend_quantity"]) >= 40


def test_forecasting_subtracts_active_pipeline_from_production_suggestion(client, auth_headers):
    color = f"forecast-pipeline-{uuid4().hex[:8]}"
    size = "XXL"
    _insert_branded_production_history(color=color, size=size, quantities=[25], status="finished_storage")
    _insert_branded_production_history(color=color, size=size, quantities=[30], status="planning")

    r = client.get("/api/forecasting/branded-stock-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((item for item in r.json() if item["color"] == color and item["size"] == size), None)
    assert row is not None
    assert int(row["historical_quantity"]) == 25
    assert int(row["pipeline_quantity"]) == 30
    assert int(row["suggested_quantity"]) == max(
        0,
        int(row["projected_demand"]) - int(row["available_quantity"]) - int(row["pipeline_quantity"]),
    )


def test_forecasting_matches_unbranded_finished_stock_through_production_order(client, auth_headers):
    color = f"forecast-stock-brand-{uuid4().hex[:8]}"
    size = "3XL"
    _insert_branded_production_history(
        color=color,
        size=size,
        quantities=[5],
        brand_id=1,
        available_qty=100,
    )

    r = client.get("/api/forecasting/branded-stock-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert not any(item["color"] == color and item["size"] == size for item in r.json())


def test_forecasting_item_reorder_suggestions_when_below_level(client, auth_headers):
    item_id, sku = _create_reorder_item(reorder_level=50)

    r = client.get("/api/forecasting/item-reorder-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((item for item in r.json() if int(item["item_id"]) == item_id), None)
    assert row is not None
    assert row["item_sku"] == sku
    assert float(row["suggested_quantity"]) >= 50
    assert "reorder level" in row["reason"]


def test_forecasting_item_reorder_uses_planned_bom_demand_without_reorder_level(client, auth_headers):
    db = SessionLocal()
    try:
        suffix = uuid4().hex[:8].upper()
        color = f"bom-forecast-{suffix}"
        item = Item(
            sku=f"FC-BOM-{suffix}",
            name=f"Forecast BOM {suffix}",
            category="fabric",
            unit="kg",
            default_cost=1,
            reorder_level=0,
            track_batch=True,
            is_active=True,
        )
        db.add(item)
        db.flush()
        db.add(
            ModelBOM(
                model_id=1,
                item_id=item.id,
                color=color,
                quantity_per_piece=0.5,
                unit="kg",
                waste_percent=0,
            )
        )
        po = ProductionOrder(
            production_no=f"PO-FC-BOM-{suffix}",
            production_type="branded_stock",
            model_id=1,
            status="planning",
            planned_quantity=20,
        )
        db.add(po)
        db.flush()
        db.add(
            ProductionOrderItem(
                production_order_id=po.id,
                model_id=1,
                color=color,
                size="M",
                planned_quantity=20,
            )
        )
        db.commit()
        item_id = int(item.id)
        sku = item.sku
    finally:
        db.close()

    r = client.get("/api/forecasting/item-reorder-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((entry for entry in r.json() if int(entry["item_id"]) == item_id), None)
    assert row is not None
    assert row["item_sku"] == sku
    assert float(row["reorder_level"]) == 0
    assert float(row["planned_bom_demand"]) == 10
    assert float(row["suggested_quantity"]) >= 10
    assert "planned BOM demand" in row["reason"]


def test_forecast_recommendation_accept_and_dismiss_state_changes(client, auth_headers):
    r = client.post(
        "/api/forecasting/recommendations",
        json={
            "recommendation_type": "item_reorder",
            "item_id": 1,
            "suggested_quantity": 12,
            "unit": "kg",
            "confidence": "medium",
            "reason": "Test recommendation",
            "source_json": {"test": True},
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    rec_id = int(r.json()["id"])

    r = client.patch(f"/api/forecasting/recommendations/{rec_id}", json={"status": "accepted"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "accepted"

    r = client.patch(f"/api/forecasting/recommendations/{rec_id}", json={"status": "dismissed"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dismissed"


def test_forecasting_permission_denied_for_manage(client):
    sales_headers = _token_headers(client, "sales@example.com")
    r = client.post(
        "/api/forecasting/recommendations",
        json={
            "recommendation_type": "item_reorder",
            "item_id": 1,
            "suggested_quantity": 1,
        },
        headers=sales_headers,
    )
    assert r.status_code == 403, r.text
