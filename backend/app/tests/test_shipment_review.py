from decimal import Decimal
from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models import (
    Customer, FinishedGoodsStock, Invoice, LegacyStockReceipt, Model, Package,
    PackageItem, SalesOrder, SalesOrderItem, Shipment, ShipmentPackage,
    ShipmentScanLog, StockReservation, Payment, Role, User,
)
from app.models.shipment_review import PackageQuantityAdjustment


@pytest.fixture
def dispatch():
    with SessionLocal() as db:
        model = Model(code="REVIEW-V1", name="Review model", status="approved")
        customer = Customer(name="<script>alert(1)</script>")
        receipt = LegacyStockReceipt(source_system="TEST", source_warehouse_id="review", source_record_id="review",
                                     source_checksum="a" * 64, source_payload={"quantity": 8})
        db.add_all([model, customer, receipt]); db.flush()
        order = SalesOrder(order_no="SO-REVIEW", customer_id=customer.id, order_type="branded_stock_sale", status="reserved", total_amount=80)
        db.add(order); db.flush()
        db.add(SalesOrderItem(sales_order_id=order.id, model_id=model.id, color="mixed", size="any",
                             quantity=8, requested_pack_count=1, unit_price=10))
        package = Package(package_no="PKG-REVIEW", barcode="REVIEW-QR", model_id=model.id, color="navy",
                          capacity=60, total_quantity=8, legacy_receipt_id=receipt.id, status="reserved")
        shipment = Shipment(shipment_no="SH-REVIEW", sales_order_id=order.id, customer_id=customer.id, status="created")
        db.add_all([package, shipment]); db.flush()
        item_ids = []
        for size in ["48", "50"]:
            item = PackageItem(package_id=package.id, model_id=model.id, color="navy", size=size, quantity=4)
            stock = FinishedGoodsStock(package_id=package.id, model_id=model.id, color="navy", size=size,
                                       quantity=4, available_qty=0, reserved_qty=4, sold_qty=0, status="reserved")
            db.add_all([item, stock]); db.flush()
            item_ids.append(item.id)
            db.add(StockReservation(sales_order_id=order.id, package_id=package.id, finished_goods_stock_id=stock.id, quantity=4))
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=8))
        db.add(ShipmentScanLog(shipment_id=shipment.id, package_id=package.id, scanned_code=package.barcode,
                              scan_result="matched"))
        db.commit()
        return {"shipment": shipment.id, "package": package.id, "items": item_ids, "order": order.id, "receipt": receipt.id}


def preparation(client, headers, data):
    response = client.get(f'/api/shipments/{data["shipment"]}/preparation', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def review_amount(client, headers, data, amount="65.00"):
    review = preparation(client, headers, data)["review"]
    response = client.post(f'/api/shipments/{data["shipment"]}/review-amount', headers=headers,
                           json={"amount": amount, "reason": "Warehouse agreed amount", "basis": review["basis"]})
    assert response.status_code == 200, response.text


def correct(client, headers, data, quantities=(3, 4), expected=8):
    return client.post(f'/api/shipments/{data["shipment"]}/packages/{data["package"]}/quantity', headers=headers,
                       json={"expected_quantity": expected, "reason": "Physical shortage found",
                             "items": [{"item_id": item, "quantity": qty} for item, qty in zip(data["items"], quantities)]})


def ship(client, headers, data):
    response = client.post(f'/api/shipments/{data["shipment"]}/ship', headers=headers)
    assert response.status_code == 200, response.text


def test_correction_financial_review_frozen_print_and_delivery(client, auth_headers, dispatch):
    response = correct(client, auth_headers, dispatch)
    assert response.status_code == 200, response.text
    assert response.json()["review"]["quantity"] == 7
    assert response.json()["review"]["amount"] == "70.00"
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        pkg = db.get(Package, dispatch["package"])
        assert pkg.total_quantity == 7 and pkg.quantity_shortfall == 1
        assert db.get(LegacyStockReceipt, dispatch["receipt"]).source_payload == {"quantity": 8}
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=pkg.id).all()
        assert sum(row.sold_qty for row in stocks) == 7
        assert all(row.available_qty == row.reserved_qty == 0 for row in stocks)
        assert db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).count() == 0
        # Subsequent catalog/order edits cannot change a dispatched printout.
        line = db.query(SalesOrderItem).filter_by(sales_order_id=dispatch["order"]).one()
        line.unit_price = 999
        db.commit()
    first = client.get(f'/api/shipments/{dispatch["shipment"]}/invoice', headers=auth_headers).json()
    assert first["quantity"] == 7 and first["amount"] == "65.00"
    assert first["lines"][0]["unit_price"] == "10.00"
    for lang in ["en", "ru", "uz"]:
        printed = client.get(f'/api/shipments/{dispatch["shipment"]}/invoice/print?lang={lang}', headers=auth_headers)
        assert printed.status_code == 200
        assert "65.00" in printed.text and "<script>alert(1)</script>" not in printed.text
        assert "&lt;script&gt;" in printed.text
    with SessionLocal() as db:
        assert db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).count() == 0
    delivered = client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers)
    assert delivered.status_code == 200, delivered.text
    assert client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers).status_code == 409
    with SessionLocal() as db:
        invoice = db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).one()
        assert invoice.amount == Decimal("65.00")


def test_zero_size_shortfall_keeps_capacity_and_rejects_whole_zero(client, auth_headers, dispatch):
    zero = correct(client, auth_headers, dispatch, (0, 0))
    assert zero.status_code == 409
    assert correct(client, auth_headers, dispatch, (0, 4)).status_code == 200
    with SessionLocal() as db:
        pkg = db.get(Package, dispatch["package"])
        assert pkg.total_quantity + pkg.quantity_shortfall == 8
        assert db.get(PackageItem, dispatch["items"][0]) is None
        assert sum(row.quantity for row in db.query(StockReservation).filter_by(package_id=pkg.id)) == 4


def test_amount_review_invalidated_by_quantity_change(client, auth_headers, dispatch):
    review_amount(client, auth_headers, dispatch)
    assert correct(client, auth_headers, dispatch).status_code == 200
    assert preparation(client, auth_headers, dispatch)["review"]["review_stale"]
    blocked = client.post(f'/api/shipments/{dispatch["shipment"]}/ship', headers=auth_headers)
    assert blocked.status_code == 409
    review_amount(client, auth_headers, dispatch, "60")
    ship(client, auth_headers, dispatch)


@pytest.mark.parametrize("payload", [{"status": "shipped"}, {"dispatch_snapshot": {"document": {"amount": "1"}}},
                                     {"id": 999}, {"packages": []}, {"shipped_at": "2026-01-01"}, {"sales_order_id": 1}])
def test_patch_cannot_bypass_dispatch_or_frozen_amount(client, auth_headers, dispatch, payload):
    base = f'/api/shipments/{dispatch["shipment"]}'
    assert client.patch(base, headers=auth_headers, json=payload).status_code == 422
    assert client.get(base + "/invoice", headers=auth_headers).status_code == 409
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    assert client.patch(base, headers=auth_headers, json=payload).status_code == 409
    assert client.patch(base, headers=auth_headers, json={"notes": "new"}).status_code == 409
    assert client.get(base + "/invoice", headers=auth_headers).json()["amount"] == "65.00"


def test_remove_release_and_rescan_does_not_reuse_old_match(client, auth_headers, dispatch):
    base = f'/api/shipments/{dispatch["shipment"]}'
    removed = client.post(base + f'/packages/{dispatch["package"]}/remove', headers=auth_headers, json={"reason": "Exclude this bag"})
    assert removed.status_code == 200, removed.text
    assert removed.json()["scanned_count"] == 0
    with SessionLocal() as db:
        assert sum(row.available_qty for row in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"])) == 8
        assert db.query(StockReservation).filter_by(package_id=dispatch["package"]).count() == 0
    # Reattach directly; previously recorded match must not allow dispatch.
    assert client.post(base + f'/add-package?package_id={dispatch["package"]}', headers=auth_headers).status_code == 200
    assert preparation(client, auth_headers, dispatch)["scanned_count"] == 0
    scanned = client.post(base + "/scan-package", headers=auth_headers, json={"code": "REVIEW-QR"})
    assert scanned.status_code == 200 and scanned.json()["scanned_count"] == 1


@pytest.mark.parametrize("status", ["paid", "partially_paid"])
def test_paid_invoice_blocks_delivery_without_mutating_data(client, auth_headers, dispatch, status):
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        db.add(Invoice(sales_order_id=dispatch["order"], invoice_no="INV-PAID", amount=80, status=status)); db.commit()
    response = client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers)
    assert response.status_code == 409 and "reconciliation" in response.text.lower()
    with SessionLocal() as db:
        assert db.get(Shipment, dispatch["shipment"]).status == "shipped"
        assert db.get(Package, dispatch["package"]).status == "shipped"
        assert db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).one().amount == Decimal("80")


def test_unpaid_invoice_reconciles_identity_and_legacy_delivery_unchanged(client, auth_headers, dispatch):
    with SessionLocal() as db:
        invoice = Invoice(sales_order_id=dispatch["order"], invoice_no="INV-EXISTING", amount=80, status="unpaid")
        db.add(invoice); db.commit(); invoice_id = invoice.id
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    assert client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Invoice, invoice_id).amount == Decimal("65")
        sh = db.get(Shipment, dispatch["shipment"])
        sh.status = "shipped"; sh.dispatch_snapshot = None
        db.get(Package, dispatch["package"]).status = "shipped"
        db.get(Invoice, invoice_id).amount = 123
        db.commit()
    assert client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Invoice, invoice_id).amount == Decimal("123")


def test_correction_rejects_growth_stale_and_foreign_reservation(client, auth_headers, dispatch):
    assert correct(client, auth_headers, dispatch, (5, 4)).status_code == 409
    assert correct(client, auth_headers, dispatch, expected=9).status_code == 409
    with SessionLocal() as db:
        other = SalesOrder(order_no="SO-OTHER-REVIEW", status="ready", total_amount=0)
        db.add(other); db.flush()
        db.query(StockReservation).filter_by(package_id=dispatch["package"]).first().sales_order_id = other.id
        db.commit()
    assert correct(client, auth_headers, dispatch).status_code == 409


def test_review_permissions_and_postdispatch_freeze(client, auth_headers, dispatch):
    token = client.post("/api/auth/token", data={"username": "planning@example.com", "password": "demo12345"})
    viewer = {"Authorization": "Bearer " + token.json()["access_token"]}
    assert correct(client, viewer, dispatch).status_code == 403
    base = f'/api/shipments/{dispatch["shipment"]}'
    doc = preparation(client, auth_headers, dispatch)["review"]
    payload = {"amount": "1", "reason": "Not authorized", "basis": doc["basis"]}
    assert client.post(base + "/review-amount", headers=viewer, json=payload).status_code == 403
    assert client.post(base + f'/packages/{dispatch["package"]}/remove', headers=viewer, json={"reason": "Not authorized"}).status_code == 403
    ship(client, auth_headers, dispatch)
    assert correct(client, auth_headers, dispatch).status_code == 409
    assert client.post(base + "/review-amount", headers=auth_headers, json=payload).status_code == 409
    assert client.get(base + "/invoice/print", headers=viewer).status_code == 403
    assert client.get(base + "/invoice/print").status_code == 401


@pytest.mark.parametrize("second", ["historical", "open", "frozen"])
def test_multiple_shipments_require_authoritative_snapshots(client, auth_headers, dispatch, second):
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        other = Shipment(shipment_no="SH-SECOND", sales_order_id=dispatch["order"],
                         status="created" if second == "open" else "shipped",
                         dispatch_snapshot={"document": {"amount": "10.00"}} if second == "frozen" else None)
        db.add(other); db.commit()
    response = client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers)
    assert response.status_code == (200 if second == "frozen" else 409), response.text
    with SessionLocal() as db:
        invoice = db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).first()
        if second == "frozen":
            assert invoice.amount == Decimal("75.00")
        else:
            assert invoice is None
            assert db.get(Shipment, dispatch["shipment"]).status == "shipped"


def test_unpaid_invoice_with_payment_also_blocks_reconciliation(client, auth_headers, dispatch):
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        invoice = Invoice(sales_order_id=dispatch["order"], invoice_no="INV-PAYMENT", amount=80, status="unpaid")
        db.add(invoice); db.flush()
        db.add(Payment(invoice_id=invoice.id, amount=1)); db.commit()
    assert client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers).status_code == 409


def test_pack_order_substitution_uses_actual_smaller_pack_and_caps_scans(client, auth_headers, dispatch):
    with SessionLocal() as db:
        original = db.get(Package, dispatch["package"])
        db.query(ShipmentScanLog).filter_by(shipment_id=dispatch["shipment"]).delete()
        for number in [1, 2]:
            receipt = LegacyStockReceipt(source_system="TEST", source_warehouse_id="review", source_record_id=f"alternative-{number}",
                                         source_checksum=str(number) * 64, source_payload={"quantity": 6})
            db.add(receipt); db.flush()
            package = Package(package_no=f"PKG-ALT-{number}", barcode=f"ALT-{number}", model_id=original.model_id,
                              color="navy", total_quantity=6, capacity=60, legacy_receipt_id=receipt.id,
                              status="received_in_storage")
            db.add(package); db.flush()
            db.add(PackageItem(package_id=package.id, model_id=package.model_id, color="navy", size="48", quantity=6))
            db.add(FinishedGoodsStock(package_id=package.id, model_id=package.model_id, color="navy", size="48",
                                       quantity=6, available_qty=6, reserved_qty=0, sold_qty=0, status="available"))
        db.commit()
    base = f'/api/shipments/{dispatch["shipment"]}'
    scanned = client.post(base + "/scan-package", headers=auth_headers, json={"code": "ALT-1"})
    assert scanned.status_code == 200 and scanned.json()["ok"], scanned.text
    prepared = preparation(client, auth_headers, dispatch)
    assert prepared["review"]["quantity"] == 6 and prepared["review"]["amount"] == "60.00"
    with SessionLocal() as db:
        assert sum(row.available_qty for row in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"])) == 8
        assert sum(row.quantity for row in db.query(StockReservation).filter_by(sales_order_id=dispatch["order"])) == 6
    assert client.post(base + "/scan-package", headers=auth_headers, json={"code": "ALT-2"}).status_code == 409
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        assert db.query(SalesOrderItem).filter_by(sales_order_id=dispatch["order"]).one().quantity == 6


@pytest.mark.parametrize("status", ["paid", "partially_paid"])
def test_matching_prepaid_invoice_delivers_without_invoice_or_payment_changes(client, auth_headers, dispatch, status):
    review_amount(client, auth_headers, dispatch)
    ship(client, auth_headers, dispatch)
    with SessionLocal() as db:
        invoice = Invoice(sales_order_id=dispatch["order"], invoice_no="INV-PREPAID-MATCH", amount=65, status=status)
        db.add(invoice); db.flush()
        payment = Payment(invoice_id=invoice.id, amount=65 if status == "paid" else 20)
        db.add(payment); db.commit()
        invoice_id, payment_id = invoice.id, payment.id
        before_invoice = {column.name: getattr(invoice, column.name) for column in Invoice.__table__.columns}
        before_payment = {column.name: getattr(payment, column.name) for column in Payment.__table__.columns}
    result = client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        invoice, payment = db.get(Invoice, invoice_id), db.get(Payment, payment_id)
        assert {column.name: getattr(invoice, column.name) for column in Invoice.__table__.columns} == before_invoice
        assert {column.name: getattr(payment, column.name) for column in Payment.__table__.columns} == before_payment


def test_positive_receipt_restores_shortfall_then_records_extra_and_rejects_retry(client, auth_headers, dispatch):
    assert correct(client, auth_headers, dispatch).status_code == 200
    base = f'/api/shipments/{dispatch["shipment"]}/packages/{dispatch["package"]}/quantity'
    for expected, quantities in [(7, (4, 4)), (8, (5, 4))]:
        payload = {"expected_quantity": expected, "reason": "Additional pieces physically received",
                   "confirm_extra_receipt": True,
                   "items": [{"item_id": item_id, "quantity": quantity} for item_id, quantity in zip(dispatch["items"], quantities)]}
        response = client.post(base, headers=auth_headers, json=payload)
        assert response.status_code == 200, response.text
        assert client.post(base, headers=auth_headers, json=payload).status_code == 409
    with SessionLocal() as db:
        package = db.get(Package, dispatch["package"])
        assert package.total_quantity == 9 and package.quantity_shortfall == 0
        assert sum(row.reserved_qty for row in db.query(FinishedGoodsStock).filter_by(package_id=package.id)) == 9
        assert sum(row.quantity for row in db.query(StockReservation).filter_by(package_id=package.id)) == 9
        evidence = db.query(PackageQuantityAdjustment).filter_by(package_id=package.id).order_by(PackageQuantityAdjustment.id).all()
        assert [row.delta for row in evidence] == [-1, 1, 1]
        assert [row.extra_receipt_quantity for row in evidence] == [0, 0, 1]
        assert evidence[1].after_json["restored_shortfall_quantity"] == 1
        assert db.get(LegacyStockReceipt, dispatch["receipt"]).source_payload == {"quantity": 8}
        evidence[-1].reason = "Rewrite evidence"
        with pytest.raises(ValueError, match="immutable"):
            db.commit()


def test_extra_receipt_requires_both_permissions_even_with_forged_confirmation(client, auth_headers, dispatch):
    with SessionLocal() as db:
        role = Role(name="Dispatch only", permissions=["storage.shipment"])
        db.add(role); db.flush()
        user = db.query(User).filter_by(email="fgs@example.com").one()
        user.role_id = role.id; user.extra_permissions = []
        db.commit()
    token = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    assert token.status_code == 200, token.text
    warehouse = {"Authorization": "Bearer " + token.json()["access_token"]}
    base = f'/api/shipments/{dispatch["shipment"]}/packages/{dispatch["package"]}/quantity'
    payload = {"expected_quantity": 8, "reason": "Physical receipt claim", "confirm_extra_receipt": True,
               "items": [{"item_id": item_id, "quantity": qty} for item_id, qty in zip(dispatch["items"], (5, 4))]}
    assert client.post(base, headers=warehouse, json=payload).status_code == 403
    payload["confirm_extra_receipt"] = False
    assert client.post(base, headers=auth_headers, json=payload).status_code == 409
    payload["confirm_extra_receipt"] = True
    payload["items"][0]["quantity"] = 10001
    assert client.post(base, headers=auth_headers, json=payload).status_code == 409
    with SessionLocal() as db:
        assert db.get(Package, dispatch["package"]).total_quantity == 8
        assert db.query(PackageQuantityAdjustment).count() == 0


def test_manual_four_piece_pack_can_receive_fifth_piece_with_immutable_evidence(client, auth_headers):
    with SessionLocal() as db:
        model = db.query(Model).filter_by(code="T-SHIRT-001").one()
        model_id, size = model.id, model.sizes[0].size
        customer_id = db.query(Customer.id).first()[0]
    receipt = client.post("/api/packages/manual-receipt", headers=auth_headers, json={
        "request_key": str(uuid4()), "model_id": model_id, "color": "White", "weight_kg": 1,
        "count": 1, "sizes": [{"size": size, "quantity": 4}], "reason": "Physical opening count",
    })
    assert receipt.status_code == 201, receipt.text
    pid = receipt.json()["print_run"]["package_ids"][0]
    sale = client.post("/api/sales-orders", headers=auth_headers, json={"customer_id": customer_id,
        "order_type": "branded_stock_sale", "items": [{"model_id": model_id, "color": "mixed", "size": "any",
                                                       "requested_pack_count": 1, "unit_price": 10}]})
    assert sale.status_code == 201, sale.text
    sh = client.post("/api/shipments", headers=auth_headers, json={"sales_order_id": sale.json()["id"]})
    assert sh.status_code == 201, sh.text
    sid = sh.json()["id"]
    with SessionLocal() as db:
        package = db.get(Package, pid)
        assert package.capacity == 4
        code = package.barcode
        item_id = db.query(PackageItem).filter_by(package_id=pid).one().id
    assert client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": code}).status_code == 200
    positive = client.post(f"/api/shipments/{sid}/packages/{pid}/quantity", headers=auth_headers, json={
        "expected_quantity": 4, "items": [{"item_id": item_id, "quantity": 5}],
        "reason": "Fifth piece physically received and counted", "confirm_extra_receipt": True,
    })
    assert positive.status_code == 200, positive.text
    with SessionLocal() as db:
        package = db.get(Package, pid)
        assert package.total_quantity == package.capacity == 5
        record = db.query(PackageQuantityAdjustment).filter_by(package_id=pid).one()
        assert record.delta == record.extra_receipt_quantity == 1
        assert record.before_json["capacity"] == 4 and record.after_json["capacity"] == 5
        assert db.query(FinishedGoodsStock).filter_by(package_id=pid).one().reserved_qty == 5
    assert client.post(f"/api/shipments/{sid}/ship", headers=auth_headers).status_code == 200
