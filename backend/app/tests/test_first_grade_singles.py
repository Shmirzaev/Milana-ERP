from uuid import uuid4

import pytest
from app.db.session import SessionLocal
from app.models import (Customer, Department, FinishedGoodsStock, Model, PackagingRecord,
                        ProductionOrder, ProductionOrderItem, SewingRecord, WorkOrder, Shipment, ShipmentPackage)
from app.tests.test_package_workflows import package_qr, stock_fingerprint


@pytest.fixture
def output():
    with SessionLocal() as db:
        model = db.query(Model).filter_by(code="T-SHIRT-001").one()
        po = ProductionOrder(production_no="PO-SINGLES", production_type="branded_stock", model_id=model.id,
                             planned_quantity=8)
        db.add(po); db.flush()
        for size, quantity in [("S", 5), ("M", 3)]:
            db.add(ProductionOrderItem(production_order_id=po.id, model_id=model.id, color="White", size=size, planned_quantity=quantity))
        sew = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter_by(code="SEW").scalar(),
                        operation="sewing", passed_qty=8, actual_output_qty=8)
        pkg = WorkOrder(production_order_id=po.id, department_id=db.query(Department.id).filter_by(code="PKG").scalar(),
                        operation="packaging", passed_qty=8, actual_output_qty=8)
        db.add_all([sew, pkg]); db.flush()
        db.add(SewingRecord(work_order_id=sew.id, input_qty=8, sewn_qty=8, passed_qty=8,
                            size_quantities=[{"size": "S", "quantity": 5}, {"size": "M", "quantity": 3}]))
        db.add(PackagingRecord(work_order_id=pkg.id, input_qty=8, packed_qty=8))
        db.commit()
        return {"production_order_id": po.id, "model_id": model.id, "color": "White", "capacity": 1,
                "stock_kind": "first_grade", "items": [{"model_id": model.id, "color": "White", "size": "S", "quantity": 1}]}


def create(client, headers, packages):
    body = {"request_key": str(uuid4()), "packages": packages}
    response = client.post("/api/packages/print-runs/create-packages", headers=headers, json=body)
    return response, body


def test_singles_share_size_budget_and_survive_receipt_sale(client, auth_headers, output):
    normal = {**output, "stock_kind": "standard", "capacity": 6, "items": [
        {**output["items"][0], "quantity": 3}, {**output["items"][0], "size": "M", "quantity": 3}]}
    assert create(client, auth_headers, [normal])[0].status_code == 201
    response, body = create(client, auth_headers, [output, output])
    assert response.status_code == 201, response.text
    run = response.json()
    assert client.post("/api/packages/print-runs/create-packages", headers=auth_headers, json=body).json() == run
    assert all(p["stock_kind"] == "first_grade" for p in run["packages"])
    assert create(client, auth_headers, [output])[0].status_code in (400, 409)
    # Neither sales nor the normal warehouse tab may offer unreceived singles.
    assert client.get("/api/sales-orders/first-grade-options", headers=auth_headers).json() == []
    assert client.get("/api/packages/warehouse-model/%s" % output["model_id"], headers=auth_headers).json()["total"] == 1
    received = client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": package_qr(run["package_ids"][0])})
    assert received.status_code == 200, received.text
    options = client.get("/api/sales-orders/first-grade-options", headers=auth_headers).json()
    assert [(r["size"], r["available"]) for r in options] == [("S", 2)]
    with SessionLocal() as db:
        customer = db.query(Customer.id).first()[0]
    sale = client.post("/api/sales-orders", headers=auth_headers, json={"customer_id": customer,
        "order_type": "branded_stock_sale", "items": [{"model_id": output["model_id"], "color": "White",
        "size": "S", "quantity": 1, "source_type": "first_grade", "unit_price": 10}]})
    assert sale.status_code == 201, sale.text
    assert client.get("/api/sales-orders/first-grade-options", headers=auth_headers).json()[0]["available"] == 1
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"])).all()
        assert sum(s.reserved_qty for s in stocks) == 1
        assert sum(s.available_qty for s in stocks) == 1
        assert sum(s.quantity for s in stocks) == 2
        reserved_id = next(s.package_id for s in stocks if s.reserved_qty)
    shipment = client.post("/api/shipments", headers=auth_headers, json={"sales_order_id": sale.json()["id"]})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    scan = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": package_qr(reserved_id)})
    assert scan.status_code == 200 and scan.json()["ok"], scan.text
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        from app.models import Package
        assert db.get(Package, reserved_id).stock_kind == "first_grade"
        assert db.get(Package, reserved_id).status == "shipped"
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=reserved_id)) == 1


def test_packaging_form_color_case_matches_production(client, auth_headers, output):
    payload = {**output, "color": "white", "items": [{**output["items"][0], "color": "white"}]}
    response, _ = create(client, auth_headers, [payload])
    assert response.status_code == 201, response.text
    assert response.json()["packages"][0]["stock_kind"] == "first_grade"


def test_grade_then_normal_cannot_reuse_size_even_with_total_room(client, auth_headers, output):
    assert create(client, auth_headers, [output] * 5)[0].status_code == 201
    normal = {**output, "stock_kind": "standard", "capacity": 3, "items": [{**output["items"][0], "quantity": 1}]}
    response, _ = create(client, auth_headers, [normal])
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "FIRST_GRADE_SIZE_EXCEEDED"


@pytest.mark.parametrize("change", ["missing_sizes", "wrong_color", "wrong_model", "multi_piece", "customer_owned"])
def test_invalid_grade_does_not_create_stock(client, auth_headers, output, change):
    with SessionLocal() as db:
        if change == "missing_sizes":
            record = db.query(SewingRecord).join(WorkOrder).filter(WorkOrder.production_order_id == output["production_order_id"]).one()
            record.size_quantities = []
        if change == "customer_owned":
            from app.models import SalesOrder
            order = SalesOrder(order_no="SO-GRADE", order_type="client_order")
            db.add(order); db.flush(); db.get(ProductionOrder, output["production_order_id"]).sales_order_id = order.id
        db.commit()
    if change == "wrong_color":
        output["color"] = "Red"; output["items"][0]["color"] = "Red"
    if change == "wrong_model": output["items"][0]["model_id"] += 1000
    if change == "multi_piece": output["capacity"] = 2; output["items"][0]["quantity"] = 2
    before = stock_fingerprint()
    result, _ = create(client, auth_headers, [output])
    assert result.status_code in (400, 409), result.text
    assert stock_fingerprint() == before


def test_labels_have_no_cover_and_explicit_page_numbers(client, auth_headers, output):
    run = create(client, auth_headers, [output] * 5)[0].json()
    before = stock_fingerprint()
    html = client.get(f'/api/packages/print-runs/{run["id"]}/label', headers=auth_headers)
    assert html.status_code == 200, html.text
    assert "PACKRUN:" not in html.text
    assert html.text.count("class='label-page'") == 2
    assert "Sahifa 1 / 2" in html.text and "Sahifa 2 / 2" in html.text
    assert html.text.count("<article") == 5
    assert "1st Grade" in html.text
    assert stock_fingerprint() == before


def test_manual_delete_releases_scanned_package_and_cannot_replay_create(client, auth_headers, output):
    run = create(client, auth_headers, [output])[0].json()
    client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": package_qr(run["package_ids"][0])})
    with SessionLocal() as db:
        customer = db.query(Customer.id).first()[0]
    body = {"manual": True, "customer_id": customer, "request_key": str(uuid4())}
    response = client.post("/api/shipments", headers=auth_headers, json=body)
    assert response.status_code == 201, response.text
    shipment = response.json()["id"]
    scan = client.post(f"/api/shipments/{shipment}/scan-package", headers=auth_headers, json={"code": package_qr(run["package_ids"][0])})
    assert scan.status_code == 200, scan.text
    before = stock_fingerprint()
    deleted = client.post(f"/api/shipments/{shipment}/delete", headers=auth_headers, json={"reason": "Created by mistake"})
    assert deleted.status_code == 200, deleted.text
    assert stock_fingerprint() == before
    assert shipment not in [r["id"] for r in client.get("/api/shipments", headers=auth_headers).json()]
    assert client.post("/api/shipments", headers=auth_headers, json=body).status_code == 410
    with SessionLocal() as db:
        assert db.get(Shipment, shipment).deleted_at is not None
        assert db.query(ShipmentPackage).filter_by(shipment_id=shipment).count() == 0


@pytest.mark.parametrize("status,manual", [("shipped", True), ("delivered", True), ("created", False)])
def test_delete_blocks_posted_and_order_shipments(client, auth_headers, status, manual):
    with SessionLocal() as db:
        sh = Shipment(shipment_no="SH-DELETE-GUARD", status=status, dispatch_snapshot={"manual": manual})
        db.add(sh); db.commit(); sid = sh.id
    response = client.post(f"/api/shipments/{sid}/delete", headers=auth_headers, json={"reason": "Created by mistake"})
    assert response.status_code == 409, response.text


def test_empty_manual_delete_and_permission_guards(client, auth_headers, output):
    with SessionLocal() as db:
        sh = Shipment(shipment_no="SH-EMPTY-MANUAL", status="created", dispatch_snapshot={"manual": True})
        db.add(sh); db.commit(); sid = sh.id
    login = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    warehouse = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert create(client, warehouse, [output])[0].status_code == 403
    login = client.post("/api/auth/token", data={"username": "sales@example.com", "password": "demo12345"})
    sales = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.post(f"/api/shipments/{sid}/delete", headers=sales, json={"reason": "Mistake"}).status_code == 403
    assert client.post(f"/api/shipments/{sid}/delete", headers=auth_headers, json={"reason": "Mistake"}).status_code == 200
    assert client.post(f"/api/shipments/{sid}/delete", headers=auth_headers, json={"reason": "Mistake"}).status_code == 404


def test_first_grade_cannot_be_increased_during_dispatch(client, auth_headers, output):
    from app.models import PackageItem
    run = create(client, auth_headers, [output])[0].json()
    client.post("/api/packages/print-runs/receive", headers=auth_headers, json={"code": package_qr(run["package_ids"][0])})
    with SessionLocal() as db:
        customer = db.query(Customer.id).first()[0]
        item = db.query(PackageItem.id).filter_by(package_id=run["package_ids"][0]).scalar()
    sh = client.post("/api/shipments", headers=auth_headers, json={"manual": True, "customer_id": customer, "request_key": str(uuid4())}).json()["id"]
    client.post(f"/api/shipments/{sh}/scan-package", headers=auth_headers, json={"code": package_qr(run["package_ids"][0])})
    before = stock_fingerprint()
    response = client.post(f'/api/shipments/{sh}/packages/{run["package_ids"][0]}/quantity', headers=auth_headers,
        json={"expected_quantity": 1, "reason": "Found extra piece", "confirm_extra_receipt": True,
              "items": [{"item_id": item, "quantity": 2}]})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "FIRST_GRADE_ONE_PIECE_REQUIRED"
    assert stock_fingerprint() == before
