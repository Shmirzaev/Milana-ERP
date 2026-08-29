from uuid import uuid4

from app.db.session import SessionLocal
from app.models import FinishedGoodsStock, LegacyStockReceipt, Package, ShipmentPackage, StockReservation


def _find_model_id(client, headers, code: str) -> int:
    r = client.get("/api/models", params={"code": code, "page_size": 1}, headers=headers)
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
        "/api/auth/token",
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
    notification = next((n for n in notifications if str(so["order_no"]) in str(n.get("title", ""))), None)
    assert notification is not None
    assert "12 pcs" in str(notification.get("title") or "")
    assert "T-SHIRT-001" in str(notification.get("message") or "")
    assert "white / 46" in str(notification.get("message") or "")
    assert "x 12" in str(notification.get("message") or "")
    assert str(notification.get("link") or "") == f"/departments/FGS#shipping-order-{so['id']}"


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


def test_manual_finished_goods_reserve_rejects_non_positive_quantity(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    brand_id = _find_brand_id(client, auth_headers, "Urban Co.")
    stock_id = _insert_finished_goods_stock(
        model_id=model_id,
        brand_id=brand_id,
        color="navy",
        size="50",
        available_qty=20,
    )

    r = client.post("/api/sales-orders", json={"order_type": "client_order", "items": []}, headers=auth_headers)
    assert r.status_code == 201, r.text
    sales_order_id = int(r.json()["id"])

    for quantity in (0, -5):
        r = client.post(
            f"/api/finished-goods/reserve?stock_id={stock_id}&quantity={quantity}&sales_order_id={sales_order_id}",
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
        assert "Quantity must be > 0" in r.text

    row = _stock_row(client, auth_headers, stock_id)
    assert int(row["available_qty"]) == 20
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


def test_branded_stock_sale_lists_and_reserves_unbranded_branded_production_stock(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"NO-BRAND-{suffix}", "name": "No brand stock model", "status": "approved"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    model_id = int(r.json()["id"])

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
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
    r = client.post(f"/api/packages/{package_id}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/finished-goods/branded-stock", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = [row for row in r.json() if int(row["model_id"]) == model_id]
    assert sum(int(row["available_qty"] or 0) for row in rows) == 60
    assert all(row["brand_id"] is None for row in rows)

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
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
        assert row.brand_id is None
        assert int(row.available_qty or 0) == 0
        assert int(row.reserved_qty or 0) == 60
    finally:
        db.close()


def test_branded_stock_sale_lists_and_reserves_legacy_receipt_stock(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"LEGACY-SALE-{suffix}", "name": "Legacy sale stock model", "status": "approved"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    model_id = int(r.json()["id"])

    db = SessionLocal()
    try:
        receipt = LegacyStockReceipt(
            source_system="TEST_LEGACY_SALE",
            source_warehouse_id="test",
            source_record_id=suffix,
            source_checksum="0" * 64,
            source_payload={"test": True},
        )
        db.add(receipt)
        db.flush()
        package = Package(
            package_no=f"LEGACY-SALE-{suffix}",
            barcode=f"LEGACY-SALE-{suffix}",
            legacy_receipt_id=receipt.id,
            model_id=model_id,
            color="Not specified",
            total_quantity=90,
            capacity=90,
            status="received_in_storage",
        )
        db.add(package)
        db.flush()
        db.add(
            FinishedGoodsStock(
                package_id=package.id,
                model_id=model_id,
                color="Not specified",
                size="M-46",
                quantity=90,
                available_qty=90,
                reserved_qty=0,
                sold_qty=0,
                status="available",
            )
        )
        db.commit()
        package_id = int(package.id)
    finally:
        db.close()

    r = client.get("/api/finished-goods/branded-stock", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next((row for row in r.json() if int(row.get("package_id") or 0) == package_id), None)
    assert row is not None
    assert int(row["model_id"]) == model_id
    assert int(row["available_qty"]) == 90
    assert row["brand_id"] is None

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
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
        row = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id).one()
        assert int(row.available_qty or 0) == 30
        assert int(row.reserved_qty or 0) == 60
    finally:
        db.close()


def test_branded_stock_sale_can_reserve_not_full_package(client, auth_headers):
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"PARTIAL-{suffix}", "name": "Partial stock model", "status": "approved"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    model_id = int(r.json()["id"])

    r = client.post(
        "/api/planning/create-branded-production",
        json={
            "production_type": "branded_stock",
            "model_id": model_id,
            "planned_quantity": 58,
            "items": [
                {"model_id": model_id, "color": "white", "size": "46", "planned_quantity": 58},
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
            "items": [{"model_id": model_id, "color": "white", "size": "46", "quantity": 58}],
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    package_id = int(r.json()["id"])

    r = client.post(f"/api/packages/{package_id}/receive-storage", headers=auth_headers)
    assert r.status_code == 200, r.text

    r = client.post(
        "/api/sales-orders",
        json={
            "order_type": "branded_stock_sale",
            "items": [
                {
                    "model_id": model_id,
                    "color": "mixed",
                    "size": "pack60",
                    "quantity": 58,
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
        assert int(row.available_qty or 0) == 0
        assert int(row.reserved_qty or 0) == 58
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
    assert int(row.get("order_quantity") or 0) == 60
    assert len(row.get("item_lines") or []) == 1
    assert int(row["item_lines"][0]["model_id"]) == model_id
    assert str(row["item_lines"][0]["model_code"]) == "T-SHIRT-001"
    assert str(row["item_lines"][0]["color"]) == "mixed"
    assert str(row["item_lines"][0]["size"]) == "pack60"
    assert int(row["item_lines"][0]["quantity"]) == 60

    notifications_response = client.get("/api/notifications?limit=30", headers=fgs_headers)
    assert notifications_response.status_code == 200, notifications_response.text
    notification = next(
        (n for n in notifications_response.json() if str(so["order_no"]) in str(n.get("title") or "")),
        None,
    )
    assert notification is not None
    assert "T-SHIRT-001" in str(notification.get("message") or "")
    assert "x 60" in str(notification.get("message") or "")
    assert "Tashkent, Sergeli district" in str(notification.get("message") or "")


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

    r = client.get("/api/shipments/eligible-orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert so_id in {int(x.get("id") or 0) for x in r.json()}

    r = client.post("/api/shipments", json={"sales_order_id": so_id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    shipment_id = int(r.json()["id"])

    r = client.get("/api/shipments/eligible-orders", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert so_id not in {int(x.get("id") or 0) for x in r.json()}

    r = client.post("/api/shipments", json={"sales_order_id": so_id}, headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "already exists" in str(r.json().get("detail", ""))

    r = client.get(f"/api/shipments/ready-packages?sales_order_id={so_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    ready_rows = r.json()
    assert any(int(x.get("id") or 0) == pkg_id for x in ready_rows)

    r = client.post(f"/api/shipments/{shipment_id}/add-ready-packages", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert int(r.json().get("added") or 0) == 1


def test_shipment_scan_accepts_unreserved_same_model_package_and_blocks_other_models(client, auth_headers):
    model_id = _find_model_id(client, auth_headers, "T-SHIRT-001")
    suffix = uuid4().hex[:8].upper()
    r = client.post(
        "/api/models",
        json={"code": f"SHIP-MISMATCH-{suffix}", "name": "Shipment mismatch model", "status": "approved"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    other_model_id = int(r.json()["id"])
    brand_id, collection_id = _create_brand_and_collection(client, auth_headers)

    def _create_ready_package(package_model_id: int, color: str) -> tuple[int, str]:
        r = client.post(
            "/api/planning/create-branded-production",
            json={
                "production_type": "branded_stock",
                "model_id": package_model_id,
                "collection_id": collection_id,
                "planned_quantity": 60,
                "items": [
                    {"model_id": package_model_id, "color": color, "size": "46", "planned_quantity": 60},
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
                "model_id": package_model_id,
                "color": color,
                "capacity": 60,
                "items": [{"model_id": package_model_id, "color": color, "size": "46", "quantity": 60}],
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

    pkg1_id, _pkg1_barcode = _create_ready_package(model_id, "white")
    pkg2_id, pkg2_barcode = _create_ready_package(model_id, "black")
    wrong_pkg_id, wrong_pkg_barcode = _create_ready_package(other_model_id, "white")

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

    r = client.post("/api/shipments", json={"sales_order_id": so1_id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    shipment_id = int(r.json()["id"])

    # Different model still returns a mismatch sign.
    r = client.post(
        f"/api/shipments/{shipment_id}/scan-package",
        json={"code": wrong_pkg_barcode},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert str(body["sign"]) == "error"
    assert "does not match" in str(body["message"]).lower()
    assert int(body.get("package_id") or 0) == wrong_pkg_id

    r = client.get(f"/api/shipments/{shipment_id}/scan-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    status_row = r.json()
    assert int(status_row["required_count"]) == 1
    assert int(status_row["remaining_count"]) == 1

    r = client.post(f"/api/shipments/{shipment_id}/ship", headers=auth_headers)
    assert r.status_code == 409, r.text
    assert "scan all shipment packages" in r.text.lower()

    # Same model can replace the originally reserved package.
    r = client.post(
        f"/api/shipments/{shipment_id}/scan-package",
        json={"code": pkg2_barcode},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert str(body["sign"]) == "success"
    assert int(body.get("package_id") or 0) == pkg2_id

    db = SessionLocal()
    try:
        link_ids = {
            int(row.package_id)
            for row in db.query(ShipmentPackage).filter(ShipmentPackage.shipment_id == shipment_id).all()
        }
        assert pkg2_id in link_ids
        assert pkg1_id not in link_ids
        reservation_package_ids = {
            int(row.package_id)
            for row in db.query(StockReservation).filter(StockReservation.sales_order_id == so1_id).all()
            if row.package_id is not None
        }
        assert reservation_package_ids == {pkg2_id}
    finally:
        db.close()

    r = client.get(f"/api/shipments/{shipment_id}/scan-status", headers=auth_headers)
    assert r.status_code == 200, r.text
    status_row = r.json()
    assert int(status_row["remaining_count"]) == 0

    r = client.post(f"/api/shipments/{shipment_id}/ship", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert str(r.json()["status"]) == "shipped"
