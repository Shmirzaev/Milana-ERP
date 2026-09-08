"""Exercise the department handoff using real routes and an isolated test DB."""

from uuid import uuid4

from app.db.session import SessionLocal
from app.models import Customer, FinishedGoodsStock, Invoice, Model, Package, PackageItem


def test_manual_packs_count_sales_review_dispatch_and_reprint(client, auth_headers):
    token = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    assert token.status_code == 200, token.text
    warehouse = {"Authorization": "Bearer " + token.json()["access_token"]}
    with SessionLocal() as db:
        model = db.query(Model).filter(Model.code == "T-SHIRT-001").one()
        model_id, size = model.id, model.sizes[0].size
        customer_id = db.query(Customer.id).first()[0]
    body = {"request_key": str(uuid4()), "model_id": model_id, "color": "White", "weight_kg": 1.5,
            "count": 2, "sizes": [{"size": size, "quantity": 4}], "reason": "Physical opening stock checked"}
    created = client.post("/api/packages/manual-receipt", headers=warehouse, json=body)
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert client.post("/api/packages/manual-receipt", headers=warehouse, json=body).json() == receipt
    run = receipt["print_run"]
    ids = run["package_ids"]
    for _ in range(2):
        label = client.get(f"/api/packages/print-runs/{run['id']}/label", headers=warehouse)
        assert label.status_code == 200, label.text
    count = client.post("/api/warehouse-stocktakes", headers=warehouse,
                        json={"request_key": str(uuid4()), "title": "New manual packs"})
    assert count.status_code in (200, 201), count.text
    count_id = count.json()["id"]
    with SessionLocal() as db:
        codes = [db.get(Package, pid).barcode for pid in ids]
        assert db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).count() == 2
    for code in codes:
        found = client.post(f"/api/warehouse-stocktakes/{count_id}/scan", headers=warehouse, json={"code": code})
        assert found.status_code == 200, found.text
        assert found.json()["row"]["result"] == "found"
    sale = client.post("/api/sales-orders", headers=auth_headers, json={
        "customer_id": customer_id, "order_type": "branded_stock_sale", "items": [{
            "model_id": model_id, "color": "mixed", "size": "any", "requested_pack_count": 2,
            "unit_price": 10, "source_type": "from_stock",
        }],
    })
    assert sale.status_code == 201, sale.text
    order = sale.json()
    assert order["items"][0]["requested_pack_count"] == 2
    assert order["items"][0]["quantity"] == 8
    shipment = client.post("/api/shipments", headers=warehouse, json={"sales_order_id": order["id"]})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    assert client.get(f"/api/shipments/{sid}/invoice", headers=warehouse).status_code == 409
    for code in codes:
        scanned = client.post(f"/api/shipments/{sid}/scan-package", headers=warehouse, json={"code": code})
        assert scanned.status_code == 200, scanned.text
        assert scanned.json()["ok"], scanned.text
    with SessionLocal() as db:
        item_id = db.query(PackageItem.id).filter_by(package_id=ids[0]).scalar()
    correction = client.post(f"/api/shipments/{sid}/packages/{ids[0]}/quantity", headers=warehouse, json={
        "expected_quantity": 4, "reason": "One missing piece counted", "items": [{"item_id": item_id, "quantity": 3}],
    })
    assert correction.status_code == 200, correction.text
    review = correction.json()["review"]
    assert review["quantity"] == 7
    amount = client.post(f"/api/shipments/{sid}/review-amount", headers=warehouse, json={
        "basis": review["basis"], "amount": "65.00", "reason": "Customer agreed final amount",
    })
    assert amount.status_code == 200, amount.text
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=warehouse)
    assert shipped.status_code == 200, shipped.text
    document = client.get(f"/api/shipments/{sid}/invoice", headers=warehouse)
    assert document.status_code == 200, document.text
    assert document.json()["quantity"] == 7 and document.json()["amount"] == "65.00"
    for lang in ("en", "ru", "uz"):
        printed = client.get(f"/api/shipments/{sid}/invoice/print?lang={lang}", headers=warehouse)
        assert printed.status_code == 200, printed.text
        assert shipment.json()["shipment_no"] in printed.text
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids)).all()
        assert sum(s.quantity for s in stocks) == 7
        assert sum(s.sold_qty for s in stocks) == 7
        assert sum(s.available_qty + s.reserved_qty for s in stocks) == 0
        assert db.query(Invoice).filter_by(sales_order_id=order["id"]).count() == 0
    delivered = client.post(f"/api/shipments/{sid}/deliver", headers=warehouse)
    assert delivered.status_code == 200, delivered.text
    posted = client.get(f"/api/shipments/{sid}/invoice", headers=warehouse).json()
    for key in ("quantity", "amount", "calculated_amount", "lines", "packages_count", "basis"):
        assert posted[key] == document.json()[key]
    assert posted["finance_posting_status"] == "posted"
    with SessionLocal() as db:
        invoices = db.query(Invoice).filter_by(sales_order_id=order["id"]).all()
        assert len(invoices) == 1 and float(invoices[0].amount) == 65
