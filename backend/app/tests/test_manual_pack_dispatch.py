"""Manual receipt, guarded deletion and scan-to-invoice regression."""
from decimal import Decimal
from app.db.session import SessionLocal
from app.models import Customer, FinishedGoodsStock, Invoice, Model, Package, Shipment
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
