from uuid import uuid4

from app.models import (Customer, FinishedGoodsStock, Model, Package, PackageItem,
                        ProductionOrder, WarehousePackReservation, Shipment, ShipmentPackage, Role, User)
from app.tests.conftest import TestSessionLocal


def fixture_pack(*, status="received_in_storage", factory="PKG", session_factory=TestSessionLocal):
    with session_factory() as db:
        marker = uuid4().hex[:12]
        customer = Customer(name=f"Reserve customer {marker}")
        model = Model(code=f"HOLD-{marker}", name="Reservation test", status="approved")
        db.add_all([customer, model]); db.flush()
        po = ProductionOrder(production_no=f"PO-HOLD-{marker}", model_id=model.id,
                             production_type="branded_stock", status="completed", planned_quantity=12)
        db.add(po); db.flush()
        pack = Package(package_no=f"PKG-HOLD-{marker}", barcode=f"HOLD-{marker}",
                       production_order_id=po.id, model_id=model.id, color="blue", total_quantity=12,
                       capacity=12, status=status, packaging_department_code=factory)
        db.add(pack); db.flush()
        for size, qty in [("M", 5), ("L", 7)]:
            db.add(PackageItem(package_id=pack.id, model_id=model.id, color="blue", size=size, quantity=qty))
            db.add(FinishedGoodsStock(package_id=pack.id, model_id=model.id, color="blue", size=size,
                                      quantity=qty, available_qty=qty, status="available"))
        db.commit()
        return pack.id, customer.id


def reserve(client, headers, package, customer, key=None):
    return client.post("/api/warehouse-reservations", json={"customer_id": customer, "package_ids": [package]},
                       headers={**headers, **({"Idempotency-Key": key} if key else {})})


def test_whole_pack_reserve_release_and_retry(client, auth_headers):
    pid, cid = fixture_pack()
    key = str(uuid4())
    response = reserve(client, auth_headers, pid, cid, key)
    assert response.status_code == 200, response.text
    assert reserve(client, auth_headers, pid, cid, key).json() == response.json()
    with TestSessionLocal() as db:
        assert db.query(WarehousePackReservation).count() == 1
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=pid).all()
        assert sum(s.reserved_qty for s in stocks) == 12
        assert sum(s.available_qty for s in stocks) == 0
    result = client.get("/api/warehouse-reservations", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["customer_id"] == cid
    assert reserve(client, auth_headers, pid, cid).status_code == 409
    assert client.post(f"/api/packages/{pid}/ship", headers=auth_headers).status_code == 409
    assert client.post(f"/api/packages/{pid}/mark-damaged", headers=auth_headers).status_code == 409
    release_headers = {**auth_headers, "Idempotency-Key": str(uuid4())}
    released = client.post("/api/warehouse-reservations/release", json={"package_ids": [pid]}, headers=release_headers)
    assert released.status_code == 200, released.text
    assert client.post("/api/warehouse-reservations/release", json={"package_ids": [pid]}, headers=release_headers).json() == released.json()
    with TestSessionLocal() as db:
        assert db.query(WarehousePackReservation).count() == 0
        assert db.get(Package, pid).status == "received_in_storage"
        assert sum(s.available_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=pid)) == 12


def test_prepare_keeps_scan_gate_and_same_customer(client, auth_headers):
    pid, cid = fixture_pack()
    assert reserve(client, auth_headers, pid, cid).status_code == 200
    payload = {"package_ids": [pid]}
    headers = {**auth_headers, "Idempotency-Key": str(uuid4())}
    prepared = client.post("/api/warehouse-reservations/prepare-shipment", json=payload, headers=headers)
    assert prepared.status_code == 200, prepared.text
    sid = prepared.json()["id"]
    assert client.post("/api/warehouse-reservations/prepare-shipment", json=payload, headers=headers).json()["id"] == sid
    with TestSessionLocal() as db:
        sh = db.get(Shipment, sid)
        assert sh.status == "created" and sh.customer_id == cid and sh.sales_order_id is None
        assert db.query(ShipmentPackage).filter_by(shipment_id=sid, package_id=pid).count() == 1
        assert db.query(WarehousePackReservation).count() == 0
    assert reserve(client, auth_headers, pid, cid).status_code == 409
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 409, shipped.text
    with TestSessionLocal() as db:
        barcode = db.get(Package, pid).barcode
    scanned = client.post(f"/api/shipments/{sid}/scan-package", json={"code": barcode}, headers=auth_headers)
    assert scanned.status_code == 200 and scanned.json()["ok"], scanned.text
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    with TestSessionLocal() as db:
        assert db.get(Package, pid).status == "shipped"
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=pid).all()
        assert sum(row.sold_qty for row in stocks) == 12
        assert sum(row.available_qty + row.reserved_qty for row in stocks) == 0


def test_mixed_customer_prepare_rolls_back_every_pack(client, auth_headers):
    p1, c1 = fixture_pack(); p2, c2 = fixture_pack()
    assert reserve(client, auth_headers, p1, c1).status_code == 200
    assert reserve(client, auth_headers, p2, c2).status_code == 200
    response = client.post("/api/warehouse-reservations/prepare-shipment", json={"package_ids": [p1, p2]}, headers=auth_headers)
    assert response.status_code == 409
    with TestSessionLocal() as db:
        assert db.query(WarehousePackReservation).count() == 2
        assert all(db.get(Package, pid).status == "reserved" for pid in [p1, p2])


def test_invalid_second_pack_rolls_back_entire_reservation(client, auth_headers):
    p1, c1 = fixture_pack(); p2, _ = fixture_pack(status="damaged")
    response = client.post("/api/warehouse-reservations", json={"customer_id": c1, "package_ids": [p1, p2]}, headers=auth_headers)
    assert response.status_code == 409
    with TestSessionLocal() as db:
        assert db.query(WarehousePackReservation).count() == 0
        assert db.get(Package, p1).status == "received_in_storage"


def test_factory_and_unauthenticated_access(client, auth_headers):
    pid, cid = fixture_pack(factory="BPK")
    assert reserve(client, auth_headers, pid, cid).status_code == 403
    assert client.get("/api/warehouse-reservations").status_code in (401, 403)
    assert client.post("/api/warehouse-reservations/release", json={"package_ids": [pid]}).status_code in (401, 403)


def test_available_search_is_before_paging(client, auth_headers):
    pid, _ = fixture_pack()
    with TestSessionLocal() as db:
        number = db.get(Package, pid).package_no
    response = client.get("/api/warehouse-reservations", params={"reserved": False, "q": number, "page_size": 1}, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1 and response.json()["rows"][0]["id"] == pid


def test_warehouse_staff_can_choose_customer_without_sales_or_shipping_access(client, auth_headers):
    pid, cid = fixture_pack()
    with TestSessionLocal() as db:
        role = Role(name="Pack reservations only", permissions=["storage.packages"])
        db.add(role); db.flush()
        user = db.query(User).filter_by(email="admin@example.com").one()
        user.role_id = role.id
        user.extra_permissions = []
        db.commit()
    assert client.get("/api/customers", headers=auth_headers).status_code == 403
    customers = client.get("/api/warehouse-reservations/customers", headers=auth_headers)
    assert customers.status_code == 200, customers.text
    assert any(row["id"] == cid for row in customers.json()["rows"])
    assert all(set(row) == {"id", "name"} for row in customers.json()["rows"])
    assert reserve(client, auth_headers, pid, cid).status_code == 200
    assert client.post("/api/warehouse-reservations/prepare-shipment", json={"package_ids": [pid]}, headers=auth_headers).status_code == 403
    assert client.post("/api/warehouse-reservations/release", json={"package_ids": [pid]}, headers=auth_headers).status_code == 200
