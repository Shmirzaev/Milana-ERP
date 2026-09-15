"""Manual receipt, guarded deletion and scan-to-invoice regression."""
from decimal import Decimal
from app.db.session import SessionLocal
from app.models import Customer, FinishedGoodsStock, Invoice, ManualPackageReceipt, Model, Package, PackagePrintRun, PackagePrintRunMember, Shipment
from app.tests.test_package_workflows import warehouse, manual_body, package_qr  # noqa: F401


def receive(client, headers, quantities=(13, 17)):
    body = manual_body()
    body.pop("sizes")
    body.pop("reason")
    body.update(count=len(quantities), pack_quantities=list(quantities))
    result = client.post("/api/packages/manual-receipt", headers=headers, json=body)
    assert result.status_code == 201, result.text
    assert client.post("/api/packages/manual-receipt", headers=headers, json=body).json() == result.json()
    return result.json()["print_run"]


def shipment(client, headers, price=None):
    with SessionLocal() as db:
        cid = db.query(Customer).first().id
        db.query(Model).filter_by(code="T-SHIRT-001").one().selling_price = price
        db.commit()
    result = client.post("/api/shipments", headers=headers, json={"manual": True, "customer_id": cid})
    assert result.status_code == 201, result.text
    assert result.json()["shipment_type"] == "manual"
    return result.json()["id"]


def test_pack_receipt_reprint_delete(client, warehouse):
    run = receive(client, warehouse)
    assert run["quantity"] == 30 and run["manual_receipt"]
    old_codes = [package_qr(pid) for pid in run["package_ids"]]
    for pid, qty in zip(run["package_ids"], (13, 17)):
        with SessionLocal() as db:
            assert db.get(Package, pid).status == "received_in_storage"
            assert sum(s.available_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=pid)) == qty
        label = client.get(f"/api/packages/{pid}/label", headers=warehouse)
        assert label.status_code == 200 and "<th>Quantity</th>" in label.text and f">{qty}</td>" in label.text
    result = client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages", headers=warehouse)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        assert not db.query(Package).filter(Package.id.in_(run["package_ids"])).count()
        assert not db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"])).count()
        saved = db.get(PackagePrintRun, run["id"])
        assert saved.deleted_at is not None and saved.package_ids == run["package_ids"]
        members = db.query(PackagePrintRunMember).filter_by(run_id=run["id"]).all()
        assert len(members) == 2 and sum(m.snapshot["quantity"] for m in members) == 30
        assert all(db.get(ManualPackageReceipt, m.snapshot["manual_receipt_id"]) for m in members)
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages", headers=warehouse).json() == {"deleted_count": 2}
    assert run["id"] not in [r["id"] for r in client.get("/api/packages/print-runs", headers=warehouse).json()]
    for path in [f"/print-runs/{run['id']}", f"/print-runs/{run['id']}/label", f"/print-runs/resolve?code={run['code']}"]:
        assert client.get("/api/packages" + path, headers=warehouse).status_code == 410
    assert client.post("/api/packages/print-runs/receive", headers=warehouse, json={"code": run["code"], "storage_cell": "A-01", "storage_shelf": "S1"}).status_code == 410
    for pid in run["package_ids"]:
        assert client.get(f"/api/packages/{pid}/label", headers=warehouse).status_code == 404


    new_run = receive(client, warehouse)
    assert new_run["run_no"] != run["run_no"]
    assert not set(old_codes) & {package_qr(pid) for pid in new_run["package_ids"]}


def test_scan_ship_invoice_once(client, warehouse):
    run = receive(client, warehouse)
    sid = shipment(client, warehouse, Decimal("2.50"))
    assert client.post(f"/api/shipments/{sid}/ship", headers=warehouse).status_code == 400
    for pid in run["package_ids"]:
        result = client.post(f"/api/shipments/{sid}/scan-package", headers=warehouse, json={"code": package_qr(pid)})
        assert result.status_code == 200 and result.json()["ok"], result.text
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages", headers=warehouse).status_code == 409
    result = client.post(f"/api/shipments/{sid}/ship", headers=warehouse)
    assert result.status_code == 200, result.text
    assert result.json()["shipment_type"] == "manual"
    with SessionLocal() as db:
        sh = db.get(Shipment, sid)
        assert db.query(Invoice).filter_by(sales_order_id=sh.sales_order_id).one().amount == Decimal("75.00")
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"])).all()
        assert sum(s.available_qty for s in stocks) == 0 and sum(s.sold_qty for s in stocks) == 30
        assert sh.dispatch_snapshot["document"]["finance_posting_status"] == "posted"
    assert client.post(f"/api/shipments/{sid}/ship", headers=warehouse).status_code == 409
    assert client.post(f"/api/shipments/{sid}/deliver", headers=warehouse).status_code == 200
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=db.get(Shipment, sid).sales_order_id).count() == 1


def test_missing_price_review_rollback(client, warehouse):
    run = receive(client, warehouse, (7,))
    sid = shipment(client, warehouse)
    assert client.post(f"/api/shipments/{sid}/scan-package", headers=warehouse, json={"code": package_qr(run["package_ids"][0])}).json()["ok"]
    assert client.post(f"/api/shipments/{sid}/ship", headers=warehouse).status_code == 409
    with SessionLocal() as db:
        assert db.get(Package, run["package_ids"][0]).status == "received_in_storage"
        assert db.get(Shipment, sid).sales_order_id is None
    review = client.get(f"/api/shipments/{sid}/preparation", headers=warehouse).json()["review"]
    result = client.post(f"/api/shipments/{sid}/review-amount", headers=warehouse, json={"amount": "29.99", "basis": review["basis"], "reason": "Agreed customer total"})
    assert result.status_code == 200, result.text
    result = client.post(f"/api/shipments/{sid}/ship", headers=warehouse)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=db.get(Shipment, sid).sales_order_id).one().amount == Decimal("29.99")


def test_invalid_inputs(client, warehouse):
    body = manual_body()
    body.pop("sizes")
    body.update(pack_quantities=[1], count=2)
    assert client.post("/api/packages/manual-receipt", headers=warehouse, json=body).status_code == 422
    body.update(pack_quantities=[0, 2])
    assert client.post("/api/packages/manual-receipt", headers=warehouse, json=body).status_code == 422
    assert client.post("/api/shipments", headers=warehouse, json={"manual": True}).status_code == 422
    assert client.post("/api/shipments", headers=warehouse, json={"manual": True, "customer_id": 99999999}).status_code == 404

def test_deleted_receipt_retry_does_not_return_active_labels(client, warehouse):
    body = manual_body()
    first = client.post("/api/packages/manual-receipt", headers=warehouse, json=body)
    assert first.status_code == 201
    run = first.json()["print_run"]
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages", headers=warehouse).status_code == 200
    retry = client.post("/api/packages/manual-receipt", headers=warehouse, json=body)
    assert retry.status_code == 410


def test_selected_labels_after_shipment_keep_client_balance(client, warehouse):
    run = receive(client, warehouse)
    first, second = run["package_ids"]
    sid = shipment(client, warehouse, Decimal("2.50"))
    assert client.post(f"/api/shipments/{sid}/scan-package", headers=warehouse, json={"code": package_qr(first)}).json()["ok"]
    assert client.post(f"/api/shipments/{sid}/ship", headers=warehouse).status_code == 200
    original = client.get(f"/api/shipments/{sid}/invoice", headers=warehouse).json()
    assert original["warehouse_person"]
    assert original["lines"][0]["size_display"] and "Mixed" not in original["lines"][0]["size_display"]
    html = client.get(f"/api/shipments/{sid}/invoice/print?lang=uz", headers=warehouse).text
    assert "Omborchi" in html and original["warehouse_person"] in html
    assert "Mixed" not in html and "Sof narxlar" not in html
    assert "Narx</th>" not in html and "Summa</th>" not in html
    target = f"/api/packages/print-runs/{run['id']}/manual-packages?package_ids={first}"
    assert client.delete(target, headers=warehouse).status_code == 200
    assert client.delete(target, headers=warehouse).json() == {"deleted_count": 1}
    remaining = client.get(f"/api/packages/print-runs/{run['id']}", headers=warehouse).json()
    assert remaining["package_ids"] == [second] and remaining["quantity"] == 17
    assert client.get(f"/api/packages/{first}/label", headers=warehouse).status_code == 410
    assert client.get(f"/api/packages/print-runs/{run['id']}/label", headers=warehouse).status_code == 200
    assert client.get(f"/api/shipments/{sid}/invoice", headers=warehouse).json() == original
    with SessionLocal() as db:
        assert db.get(Package, first).status == "shipped"
        assert db.query(Invoice).filter_by(sales_order_id=db.get(Shipment, sid).sales_order_id).one().amount == Decimal("32.50")
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages?package_ids={second}", headers=warehouse).status_code == 200
    with SessionLocal() as db:
        assert db.get(Package, second) is None and db.get(Package, first) is not None


def test_manual_add_client_and_selected_unused_pack(client, warehouse):
    result = client.post("/api/shipments/customers", headers=warehouse, json={"name": "New warehouse client", "phone": "123"})
    assert result.status_code == 201, result.text
    assert result.json() in client.get("/api/shipments/customers", headers=warehouse).json()
    assert client.post("/api/shipments/customers", json={"name": "Denied"}).status_code == 401
    assert client.post("/api/shipments/customers", headers=warehouse, json={"name": " "}).status_code == 422
    run = receive(client, warehouse)
    first, second = run["package_ids"]
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages?package_ids=9999999", headers=warehouse).status_code == 422
    assert client.delete(f"/api/packages/print-runs/{run['id']}/manual-packages?package_ids={first}", headers=warehouse).status_code == 200
    assert client.get(f"/api/packages/print-runs/{run['id']}", headers=warehouse).json()["package_ids"] == [second]
