from uuid import uuid4

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, Package


def _find_model_id(client, headers, code: str) -> int:
    r = client.get("/api/models", headers=headers)
    assert r.status_code == 200, r.text
    row = next((m for m in r.json() if str(m.get("code")) == code), None)
    assert row is not None, f"Model {code} not found"
    return int(row["id"])


def _find_brand_id(client, headers, name: str) -> int:
    r = client.get("/api/brands", headers=headers)
    assert r.status_code == 200, r.text
    row = next((b for b in r.json() if str(b.get("name")) == name), None)
    assert row is not None, f"Brand {name} not found"
    return int(row["id"])


def _create_brand_and_collection(client, headers) -> tuple[int, int]:
    suffix = uuid4().hex[:8]
    r = client.post(
        "/api/brands",
        json={"name": f"Repair Brand {suffix}", "description": "test"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    brand_id = int(r.json()["id"])

    r = client.post(
        "/api/collections",
        json={
            "brand_id": brand_id,
            "name": f"Repair Collection {suffix}",
            "season": "SS",
            "year": 2026,
            "status": "approved",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return brand_id, int(r.json()["id"])


def _insert_finished_goods_stock(*, model_id: int, brand_id: int, color: str, size: str, available_qty: int) -> int:
    db = SessionLocal()
    try:
        row = FinishedGoodsStock(
            model_id=model_id,
            brand_id=brand_id,
            color=color,
            size=size,
            quantity=available_qty,
            available_qty=available_qty,
            reserved_qty=0,
            sold_qty=0,
            cost_per_piece=5,
            selling_price=12,
            status="available",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def _stock_row(client, headers, stock_id: int):
    r = client.get("/api/finished-goods", headers=headers)
    assert r.status_code == 200, r.text
    row = next((s for s in r.json() if int(s["id"]) == int(stock_id)), None)
    assert row is not None, f"Stock row {stock_id} not found"
    return row


def _fgs_headers(client) -> dict[str, str]:
    r = client.post(
        "/api/auth/login",
        data={"username": "fgs@example.com", "password": "demo12345"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_branded_sales_order_auto_reserves_and_notifies_storage(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id = _find_brand_id(client, auth_headers, "Urban Co.")
    stock_id = _insert_finished_goods_stock(
        model_id=model_id,
        brand_id=brand_id,
        color="white",
        size="46",
        available_qty=30,
    )

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "white",
                    "size": "46",
                    "quantity": 12,
                    "unit_price": 19,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["status"] == "ready"

    row = _stock_row(client, auth_headers, stock_id)
    assert int(row["available_qty"]) == 18
    assert int(row["reserved_qty"]) == 12

    r2 = client.post(f"/api/sales-orders/{so['id']}/reserve-stock", headers=auth_headers)
    assert r2.status_code == 409, r2.text

    fgs_headers = _fgs_headers(client)
    r3 = client.get("/api/notifications?limit=30", headers=fgs_headers)
    assert r3.status_code == 200, r3.text
    notifications = r3.json()
    assert any(str(so["order_no"]) in str(n.get("title", "")) for n in notifications)


def test_branded_sales_order_rejects_when_stock_is_insufficient(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id = _find_brand_id(client, auth_headers, "Urban Co.")
    stock_id = _insert_finished_goods_stock(
        model_id=model_id,
        brand_id=brand_id,
        color="black",
        size="48",
        available_qty=5,
    )

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "black",
                    "size": "48",
                    "quantity": 9,
                    "unit_price": 17,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 409, r.text
    assert "Not enough branded stock" in r.text

    row = _stock_row(client, auth_headers, stock_id)
    assert int(row["available_qty"]) == 5
    assert int(row["reserved_qty"]) == 0


def test_branded_sales_order_repairs_legacy_stock_brand_metadata(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id, collection_id = _create_brand_and_collection(client, auth_headers)

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "collection_id": collection_id,
            "planned_quantity": 60,
            "items": [
                {"model_id": model_id, "color": "white", "size": "46", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": model_id,
            "color": "white",
            "capacity": 60,
            "items": [{"model_id": model_id, "color": "white", "size": "46", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    package_id = int(r.json()["id"])

    db = SessionLocal()
    try:
        row = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).first()
        assert row is not None
        row.brand_id = None
        row.collection_id = None
        pkg = db.get(Package, package_id)
        assert pkg is not None
        pkg.brand_id = None
        pkg.collection_id = None
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "mixed",
                    "size": "pack60",
                    "quantity": 60,
                    "unit_price": 21,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "ready"

    db = SessionLocal()
    try:
        row = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).first()
        assert row is not None
        assert int(row.brand_id or 0) == brand_id
        assert int(row.collection_id or 0) == collection_id
        assert int(row.available_qty or 0) == 0
        assert int(row.reserved_qty or 0) == 60
    finally:
        db.close()


def test_fgs_inbox_shows_branded_sales_prep_queue_with_reserved_qty(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id, collection_id = _create_brand_and_collection(client, auth_headers)
    r = client.post(
        "/api/customers",
        json={
            "name": "Ship Target LLC",
            "phone": "+998900000001",
            "email": "ship@example.com",
            "address": "Tashkent, Sergeli district",
            "notes": "priority",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    customer_id = int(r.json()["id"])

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "collection_id": collection_id,
            "planned_quantity": 60,
            "items": [
                {"model_id": model_id, "color": "white", "size": "46", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": model_id,
            "color": "white",
            "capacity": 60,
            "items": [{"model_id": model_id, "color": "white", "size": "46", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg_id = int(r.json()["id"])

    r = client.post(f"/api/packages/{pkg_id}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/sales-orders",
        json={
            "customer_id": customer_id,
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "mixed",
                    "size": "pack60",
                    "quantity": 60,
                    "unit_price": 22,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["status"] == "ready"
    so_id = int(so["id"])

    db = SessionLocal()
    try:
        pkg = db.get(Package, pkg_id)
        assert pkg is not None
        assert pkg.sales_order_id is None
    finally:
        db.close()

    fgs_headers = _fgs_headers(client)
    r = client.get("/api/inbox?dept=FGS", headers=fgs_headers)
    assert r.status_code == 200, r.text
    rows = r.json().get("ready_to_ship", [])
    row = next((x for x in rows if int(x.get("sales_order_id") or 0) == so_id), None)
    assert row is not None
    assert str(row.get("customer_name") or "") == "Ship Target LLC"
    assert str(row.get("destination") or "") == "Tashkent, Sergeli district"
    assert str(row.get("shipment_type") or "") == "from_stock"
    assert str(row.get("shipment_status") or "") == "not_created"
    assert int(row.get("quantity") or 0) == 60
    assert int(row.get("packages") or 0) == 1
    assert int(row.get("pending_qty") or 0) == 0


def test_shipments_ready_packages_follow_stock_reservations(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id, collection_id = _create_brand_and_collection(client, auth_headers)

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "collection_id": collection_id,
            "planned_quantity": 60,
            "items": [
                {"model_id": model_id, "color": "white", "size": "46", "planned_quantity": 60},
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    po_id = int(r.json()["id"])

    r = client.post(
        "/api/packages",
        json={
            "production_order_id": po_id,
            "model_id": model_id,
            "color": "white",
            "capacity": 60,
            "items": [{"model_id": model_id, "color": "white", "size": "46", "quantity": 60}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    pkg_id = int(r.json()["id"])

    r = client.post(f"/api/packages/{pkg_id}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "brand_id": brand_id,
                    "color": "mixed",
                    "size": "pack60",
                    "quantity": 60,
                    "unit_price": 22,
                }
            ],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    so_id = int(r.json()["id"])

    db = SessionLocal()
    try:
        pkg = db.get(Package, pkg_id)
        assert pkg is not None
        assert pkg.sales_order_id is None
    finally:
        db.close()

    r = client.post("/api/shipments", json={"sales_order_id": so_id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    shipment_id = int(r.json()["id"])

    r = client.get(f"/api/shipments/ready-packages?sales_order_id={so_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    ready_rows = r.json()
    assert any(int(x.get("id") or 0) == pkg_id for x in ready_rows)

    r = client.post(f"/api/shipments/{shipment_id}/add-ready-packages", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json().get("added") or 0) == 1


def test_shipment_scan_verifies_order_match_and_blocks_unscanned_ship(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id, collection_id = _create_brand_and_collection(client, auth_headers)

    def _create_ready_package(color: str) -> tuple[int, str]:
        r = client.post(
            "/api/planning/create-branded-production",
            json={
                "production_type": "branded_stock",
                "model_id": model_id,
                "collection_id": collection_id,
                "planned_quantity": 60,
                "items": [
                    {"model_id": model_id, "color": color, "size": "46", "planned_quantity": 60},
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        po_id = int(r.json()["id"])

        r = client.post(
            "/api/packages",
            json={
                "production_order_id": po_id,
                "model_id": model_id,
                "color": color,
                "capacity": 60,
                "items": [{"model_id": model_id, "color": color, "size": "46", "quantity": 60}],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        pkg = r.json()
        pkg_id = int(pkg["id"])
        barcode = str(pkg["barcode"])

        r = client.post(f"/api/packages/{pkg_id}/receive-storage", headers=auth_headers)
        assert r.status_code == 200, r.text
        return pkg_id, barcode

    pkg1_id, pkg1_barcode = _create_ready_package("white")
    pkg2_id, pkg2_barcode = _create_ready_package("black")

    def _create_branded_sales_order() -> int:
        r = client.post(
            "/api/sales-orders",
            json={
                "order_type": "branded_stock_sale",
                "items": [
                    {
                        "model_id": model_id,
                        "brand_id": brand_id,
                        "color": "mixed",
                        "size": "pack60",
                        "quantity": 60,
                        "unit_price": 24,
                    }
                ],
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return int(r.json()["id"])

    so1_id = _create_branded_sales_order()
    so2_id = _create_branded_sales_order()
    assert so1_id != so2_id

    r = client.post("/api/shipments", json={"sales_order_id": so1_id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    shipment_id = int(r.json()["id"])

    # Wrong package scan should return a mismatch sign.
    r = client.post(
        f"/api/shipments/{shipment_id}/scan-package",
        json={"code": pkg2_barcode},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert str(body["sign"]) == "error"
    assert "does not belong" in str(body["message"]).lower()
    assert int(body.get("package_id") or 0) == pkg2_id

    # Add target order packages and verify ship is blocked until they are scanned.
    r = client.post(f"/api/shipments/{shipment_id}/add-ready-packages", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json().get("added") or 0) >= 1

    r = client.get(f"/api/shipments/{shipment_id}/scan-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    status_row = r.json()
    assert int(status_row["required_count"]) >= 1
    assert int(status_row["remaining_count"]) >= 1

    r = client.post(f"/api/shipments/{shipment_id}/ship", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "scan all shipment packages" in r.text.lower()

    r = client.post(
        f"/api/shipments/{shipment_id}/scan-package",
        json={"code": pkg1_barcode},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert str(body["sign"]) == "success"
    assert int(body.get("package_id") or 0) == pkg1_id

    r = client.get(f"/api/shipments/{shipment_id}/scan-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    status_row = r.json()
    assert int(status_row["remaining_count"]) == 0

    r = client.post(f"/api/shipments/{shipment_id}/ship", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert str(r.json()["status"]) == "shipped"
