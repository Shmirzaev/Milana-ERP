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


def size_entry_path(output):
    path = f'/api/packages/first-grade/size-entry/{output["production_order_id"]}'
    return path + (f'?production_batch_id={output["production_batch_id"]}' if output.get("production_batch_id") else "")


def missing_size_evidence(output):
    with SessionLocal() as db:
        row = db.query(SewingRecord).join(WorkOrder).filter(WorkOrder.production_order_id == output["production_order_id"]).one()
        row.size_quantities = []
        db.commit()
        return row.id


def save_sizes(client, headers, output, sizes=None, version=None):
    path = size_entry_path(output)
    if version is None:
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        version = response.json()["version"]
    return client.put(path, headers=headers, json={"version": version, "sizes": sizes if sizes is not None else [
        {"size": "S", "quantity": 5}, {"size": "M", "quantity": 3}]})


def test_packaging_enters_missing_sizes_without_mutating_sewing_then_receives_and_sells(client, auth_headers, output):
    rid = missing_size_evidence(output)
    state = client.get(size_entry_path(output), headers=auth_headers).json()
    assert state["needs_size_entry"] and state["total"] == 8
    assert all(row["accepted"] is None for row in state["sizes"])
    before = stock_fingerprint()
    saved = save_sizes(client, auth_headers, output)
    assert saved.status_code == 200, saved.text
    assert not saved.json()["needs_size_entry"]
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.get(SewingRecord, rid).size_quantities == []
        assert db.get(SewingRecord, rid).passed_qty == 8
        from app.models import AuditLog
        assert db.query(AuditLog).filter_by(entity_type="ProductionOrder", entity_id=output["production_order_id"], action="update").count() == 1
    # Exercise the complete normal pack -> singles -> receipt -> sale -> shipment handoff.
    test_singles_share_size_budget_and_survive_receipt_sale(client, auth_headers, output)


@pytest.mark.parametrize("sizes,status", [
    ([{"size": "S", "quantity": 6}, {"size": "M", "quantity": 3}], 409),
    ([{"size": "S", "quantity": 4}, {"size": "M", "quantity": 3}], 409),
    ([{"size": "S", "quantity": -1}, {"size": "M", "quantity": 9}], 422),
    ([{"size": "S", "quantity": 5.5}, {"size": "M", "quantity": 2.5}], 422),
    ([{"size": "S", "quantity": 5}, {"size": "S", "quantity": 3}], 422),
    ([{"size": "XL", "quantity": 8}], 422),
])
def test_packaging_size_input_validation(client, auth_headers, output, sizes, status):
    missing_size_evidence(output)
    before = stock_fingerprint()
    response = save_sizes(client, auth_headers, output, sizes)
    assert response.status_code == status, response.text
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.get(ProductionOrder, output["production_order_id"]).packaging_size_breakdowns is None


def test_packaging_size_entry_counts_existing_packs_and_rejects_stale_submissions(client, auth_headers, output):
    missing_size_evidence(output)
    normal = {**output, "stock_kind": "standard", "capacity": 3,
              "items": [{**output["items"][0], "quantity": 3}]}
    initial = client.get(size_entry_path(output), headers=auth_headers).json()
    assert create(client, auth_headers, [normal])[0].status_code == 201
    assert save_sizes(client, auth_headers, output, version=initial["version"]).json()["detail"] == "FIRST_GRADE_SIZE_STALE"
    response = save_sizes(client, auth_headers, output, [{"size": "S", "quantity": 2}, {"size": "M", "quantity": 6}])
    assert response.status_code == 409 and response.json()["detail"] == "FIRST_GRADE_SIZE_PACKED"
    saved = save_sizes(client, auth_headers, output)
    assert saved.status_code == 200, saved.text
    assert next(row for row in saved.json()["sizes"] if row["size"] == "S")["remaining"] == 2
    assert create(client, auth_headers, [output] * 3)[0].status_code == 409
    assert create(client, auth_headers, [output] * 2)[0].status_code == 201


def test_packaging_size_snapshot_invalidates_when_sewing_output_changes(client, auth_headers, output):
    rid = missing_size_evidence(output)
    assert save_sizes(client, auth_headers, output).status_code == 200
    with SessionLocal() as db:
        row = db.get(SewingRecord, rid)
        row.passed_qty = 7
        db.commit()
    state = client.get(size_entry_path(output), headers=auth_headers).json()
    assert state["needs_size_entry"] and state["total"] == 7
    assert create(client, auth_headers, [output])[0].status_code == 409
    assert save_sizes(client, auth_headers, output, [{"size": "S", "quantity": 4}, {"size": "M", "quantity": 3}]).status_code == 200


def test_packaging_size_entry_batch_scope_and_legacy_sewing_batch(client, auth_headers, output):
    from app.models import ProductionBatch
    rid = missing_size_evidence(output)
    with SessionLocal() as db:
        batch = ProductionBatch(production_order_id=output["production_order_id"], batch_no="SINGLE-01", planned_quantity=8)
        sibling = ProductionBatch(production_order_id=output["production_order_id"], batch_no="SINGLE-02", batch_index=2, planned_quantity=8)
        db.add_all([batch, sibling]); db.flush()
        row = db.get(SewingRecord, rid)
        db.get(WorkOrder, row.work_order_id).production_batch_id = batch.id
        db.commit()
        bid, sibling_id = batch.id, sibling.id
    assert client.get(size_entry_path(output), headers=auth_headers).json()["detail"] == "FIRST_GRADE_BATCH_REQUIRED"
    output["production_batch_id"] = bid
    assert save_sizes(client, auth_headers, output).status_code == 200
    sibling_state = client.get(size_entry_path({**output, "production_batch_id": sibling_id}), headers=auth_headers).json()
    assert sibling_state["needs_size_entry"] and sibling_state["total"] == 0
    assert save_sizes(client, auth_headers, {**output, "production_batch_id": sibling_id}).status_code == 409
    assert client.get(size_entry_path({**output, "production_batch_id": 99999999}), headers=auth_headers).status_code == 404


def test_packaging_size_entry_requires_packaging_permission_and_matching_factory(client, auth_headers, output):
    from app.models import User, Role
    missing_size_evidence(output)
    state = client.get(size_entry_path(output), headers=auth_headers).json()
    body = {"version": state["version"], "sizes": [{"size": "S", "quantity": 8}]}
    for email in ("fgs@example.com", "sales@example.com"):
        login = client.post("/api/auth/token", data={"username": email, "password": "demo12345"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        assert client.get(size_entry_path(output), headers=headers).status_code == 403
        assert client.put(size_entry_path(output), headers=headers, json=body).status_code == 403
    # A packaging-only operator can supply this evidence without Sewing access.
    with SessionLocal() as db:
        user = db.query(User).filter_by(email="fgs@example.com").one()
        role = Role(name="Size Entry Packaging", permissions=["packaging.packages"])
        db.add(role); db.flush(); user.role_id = role.id
        user.department_id = db.query(Department.id).filter_by(code="PKG").scalar()
        db.commit()
    login = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert save_sizes(client, headers, output).status_code == 200
    with SessionLocal() as db:
        other = db.query(Department).filter_by(code="BPK").one_or_none()
        if other is None:
            other = Department(code="BPK", name="Besttex Packaging"); db.add(other); db.flush()
        db.query(WorkOrder).filter_by(production_order_id=output["production_order_id"], operation="packaging").one().department_id = other.id
        db.commit()
    assert client.get(size_entry_path(output), headers=headers).status_code == 403
    assert client.put(size_entry_path(output), headers=headers, json=body).status_code == 403
