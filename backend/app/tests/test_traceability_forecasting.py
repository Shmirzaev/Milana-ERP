from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, Item, SalesOrder, SalesOrderItem, StockMovement


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


def test_forecasting_item_reorder_suggestions_when_below_level(client, auth_headers):
    item_id, sku = _create_reorder_item(reorder_level=50)

    r = client.get("/api/forecasting/item-reorder-suggestions", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((item for item in r.json() if int(item["item_id"]) == item_id), None)
    assert row is not None
    assert row["item_sku"] == sku
    assert float(row["suggested_quantity"]) >= 50
    assert "reorder level" in row["reason"]


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
