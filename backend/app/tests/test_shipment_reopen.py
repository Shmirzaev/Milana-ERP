from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import AuditLog, FinishedGoodsStock, IdempotencyRecord, Invoice, Package, Payment, SalesOrder, Shipment, ShipmentScanLog
from app.services.payments import create_invoice_payment
from app.tests.test_manual_pack_dispatch import receive, shipment
from app.tests.test_package_workflows import warehouse, package_qr  # noqa: F401
from app.tests.test_shipment_review import correct, dispatch, review_amount  # noqa: F401


def payload(result):
    return {"reason": "All goods returned for correction", "packages_returned": True,
            "expected_shipped_at": result["shipped_at"]}


def test_reopen_invalidates_legacy_and_scoped_scan_results_with_only_package_identity(client, warehouse):
    run = receive(client, warehouse)
    sid = shipment(client, warehouse, None)
    url = f"/api/shipments/{sid}"
    for pid in run["package_ids"]:
        scanned = client.post(url + "/scan-package", headers=warehouse, json={"code": package_qr(pid)})
        assert scanned.status_code == 200 and scanned.json()["ok"], scanned.text
    shipped = client.post(url + "/ship", headers=warehouse)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        scopes = ["shipments.scan-package", "shipments.scan-package:v2:" + "a" * 64, "shipments.other:v2:" + "b" * 64]
        records = [IdempotencyRecord(scope=scope, key="fn06-invalidation", request_hash="c" * 64,
                                    response_json={"package_id": run["package_ids"][0]}) for scope in scopes]
        db.add_all(records)
        db.commit()
        ids = [record.id for record in records]
    reopened = client.post(url + "/reopen", headers=warehouse, json=payload(shipped.json()))
    assert reopened.status_code == 200, reopened.text
    with SessionLocal() as db:
        hashes = [db.get(IdempotencyRecord, rid).request_hash for rid in ids]
        assert hashes[0] != "c" * 64 and hashes[1] != "c" * 64
        assert hashes[2] == "c" * 64


@pytest.mark.parametrize("price,delivered", [(None, False), (None, True), (Decimal("2.5"), False), (Decimal("2.5"), True)])
def test_manual_return_and_redispatch(client, auth_headers, warehouse, price, delivered):
    run = receive(client, warehouse)
    sid = shipment(client, warehouse, price)
    url = f"/api/shipments/{sid}"
    for pid in run["package_ids"]:
        response = client.post(url + "/scan-package", headers={**warehouse, "Idempotency-Key": f"scan-{pid}"}, json={"code": package_qr(pid)})
        assert response.json()["ok"], response.text
    shipped = client.post(url + "/ship", headers={**warehouse, "Idempotency-Key": "first-dispatch"})
    assert shipped.status_code == 200, shipped.text
    if delivered:
        assert client.post(url + "/deliver", headers=warehouse).status_code == 200
    with SessionLocal() as db:
        old_order = db.get(Shipment, sid).sales_order_id
        ids = [s.id for s in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(run["package_ids"]))]
        scans = [(s.id, s.package_id, s.scan_result, s.scanned_at, s.scanned_by)
                 for s in db.query(ShipmentScanLog).filter_by(shipment_id=sid).order_by(ShipmentScanLog.id)]
    body = payload(shipped.json())
    result = client.post(url + "/reopen", headers=warehouse, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "created" and result.json()["shipment_type"] == "manual"
    assert result.json()["shipped_at"] is None and result.json()["delivered_at"] is None
    assert result.json()["scanned_count"] == 2 and result.json()["packages_count"] == 2
    preparation = client.get(url + "/preparation", headers=warehouse).json()
    assert preparation["scanned_count"] == 2 and preparation["review"]["quantity"] == 30
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.id.in_(ids)).all()
        assert sum(s.available_qty for s in stocks) == 30 and sum(s.sold_qty for s in stocks) == 0
        assert all(db.get(Package, pid).status == "received_in_storage" for pid in run["package_ids"])
        assert db.get(Shipment, sid).sales_order_id is None
        evidence = db.query(AuditLog).filter_by(action="reopen_shipment", entity_id=sid).one()
        assert evidence.old_value_json["dispatch_snapshot"]["document"]["quantity"] == 30
        assert evidence.new_value_json["rescan_required"] is False
        assert scans == [(s.id, s.package_id, s.scan_result, s.scanned_at, s.scanned_by)
                         for s in db.query(ShipmentScanLog).filter_by(shipment_id=sid).order_by(ShipmentScanLog.id)]
        if old_order:
            invoice = db.query(Invoice).filter_by(sales_order_id=old_order).one()
            assert invoice.status == "void" and invoice.amount == 0
            assert db.get(SalesOrder, old_order).total_amount == 0
            with pytest.raises(HTTPException):
                create_invoice_payment(db, invoice, amount=1)
            assert db.query(Payment).filter_by(invoice_id=invoice.id).count() == 0
    if old_order:
        rejected = client.post("/api/finance/payments", headers=auth_headers,
                               json={"invoice_id": invoice.id, "amount": 1})
        assert rejected.status_code == 409, rejected.text
        with SessionLocal() as db:
            assert db.query(Payment).filter_by(invoice_id=invoice.id).count() == 0
    assert client.post(url + "/reopen", headers=warehouse, json=body).status_code == 409
    assert client.post(url + "/ship", headers={**warehouse, "Idempotency-Key": "first-dispatch"}).status_code == 409
    for pid in run["package_ids"]:
        assert client.post(url + "/scan-package", headers={**warehouse, "Idempotency-Key": f"scan-{pid}"}, json={"code": package_qr(pid)}).status_code == 409
    result = client.post(url + "/ship", headers=warehouse)
    assert result.status_code == 200, result.text
    assert client.post(url + "/reopen", headers=warehouse, json=body).status_code == 409
    assert client.post(url + "/deliver", headers=warehouse).status_code == 200
    with SessionLocal() as db:
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.id.in_(ids))) == 30
        if price:
            order_id = db.get(Shipment, sid).sales_order_id
            assert order_id != old_order
            assert db.query(Invoice).filter_by(sales_order_id=order_id).one().amount == Decimal("75")


def test_order_return_preserves_reservations_and_can_invoice_again(client, auth_headers, dispatch):
    url = f'/api/shipments/{dispatch["shipment"]}'
    first = client.post(url + "/ship", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert client.post(url + "/deliver", headers=auth_headers).status_code == 200
    result = client.post(url + "/reopen", headers=auth_headers, json=payload(first.json()))
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        assert db.get(Shipment, dispatch["shipment"]).sales_order_id == dispatch["order"]
        assert db.get(SalesOrder, dispatch["order"]).status == "ready_to_ship"
        assert sum(s.reserved_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"])) == 8
    assert result.json()["scanned_count"] == 1
    assert client.post(url + "/ship", headers=auth_headers).status_code == 200
    result = client.post(url + "/deliver", headers=auth_headers)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        invoices = db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).all()
        assert len(invoices) == 2 and sum(i.amount for i in invoices) == 80


def test_returned_shipment_edits_keep_scans_and_reset_agreed_total(client, auth_headers, dispatch):
    url = f'/api/shipments/{dispatch["shipment"]}'
    review_amount(client, auth_headers, dispatch)
    first = client.post(url + "/ship", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert client.post(url + "/reopen", headers=auth_headers, json=payload(first.json())).status_code == 200
    edited = correct(client, auth_headers, dispatch)
    assert edited.status_code == 200, edited.text
    assert edited.json()["scanned_count"] == 1
    assert edited.json()["review"]["quantity"] == 7
    assert edited.json()["review"]["amount"] == "70.00"
    assert client.patch(url, headers=auth_headers, json={"notes": "Corrected after return"}).status_code == 200
    result = client.post(url + "/ship", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert client.get(url + "/invoice", headers=auth_headers).json()["quantity"] == 7


@pytest.mark.parametrize("remove_existing", [False, True])
def test_return_does_not_verify_added_or_removed_packages(client, warehouse, remove_existing):
    run = receive(client, warehouse)
    sid = shipment(client, warehouse)
    url = f"/api/shipments/{sid}"
    original, extra = run["package_ids"]
    assert client.post(url + "/scan-package", headers=warehouse, json={"code": package_qr(original)}).json()["ok"]
    first = client.post(url + "/ship", headers=warehouse)
    assert first.status_code == 200, first.text
    assert client.post(url + "/reopen", headers=warehouse, json=payload(first.json())).status_code == 200
    target = extra
    if remove_existing:
        target = original
        removed = client.post(url + f"/packages/{original}/remove", headers=warehouse,
                              json={"reason": "Remove returned package"})
        assert removed.status_code == 200, removed.text
    assert client.post(url + f"/add-package?package_id={target}", headers=warehouse).status_code == 200
    preparation = client.get(url + "/preparation", headers=warehouse).json()
    assert preparation["scanned_count"] == (0 if remove_existing else 1)
    assert client.post(url + "/ship", headers=warehouse).status_code == 409
    scanned = client.post(url + "/scan-package", headers=warehouse, json={"code": package_qr(target)})
    assert scanned.json()["ok"], scanned.text
    second = client.post(url + "/ship", headers=warehouse)
    assert second.status_code == 200, second.text
    # A second complete return also preserves only the current verified links.
    returned = client.post(url + "/reopen", headers=warehouse, json=payload(second.json()))
    assert returned.status_code == 200, returned.text
    assert returned.json()["scanned_count"] == (1 if remove_existing else 2)
    assert client.post(url + "/ship", headers=warehouse).status_code == 200


@pytest.mark.parametrize("block", ["payment", "external", "stock", "shared"])
def test_reopen_guards_atomicity_and_permissions(client, warehouse, block):
    run = receive(client, warehouse, (7,))
    sid = shipment(client, warehouse, Decimal("2"))
    url = f"/api/shipments/{sid}"
    assert client.post(url + "/scan-package", headers=warehouse, json={"code": package_qr(run["package_ids"][0])}).json()["ok"]
    first = client.post(url + "/ship", headers=warehouse)
    assert first.status_code == 200
    body = payload(first.json())
    assert client.post(url + "/reopen", json=body).status_code == 401
    token = client.post("/api/auth/token", data={"username": "planning@example.com", "password": "demo12345"})
    viewer = {"Authorization": "Bearer " + token.json()["access_token"]}
    assert client.post(url + "/reopen", headers=viewer, json=body).status_code == 403
    assert client.post(url + "/reopen", headers=warehouse, json={**body, "packages_returned": False}).status_code == 409
    with SessionLocal() as db:
        sh = db.get(Shipment, sid)
        inv = db.query(Invoice).filter_by(sales_order_id=sh.sales_order_id).one()
        if block == "payment": db.add(Payment(invoice_id=inv.id, amount=1))
        if block == "external": inv.external_id = "exported"
        if block == "stock": db.query(FinishedGoodsStock).filter_by(package_id=run["package_ids"][0]).one().sold_qty = 6
        if block == "shared": db.add(Shipment(shipment_no="SH-OTHER", sales_order_id=sh.sales_order_id, status="created"))
        db.commit()
    result = client.post(url + "/reopen", headers=warehouse, json=body)
    assert result.status_code == 409, result.text
    with SessionLocal() as db:
        assert db.get(Shipment, sid).status == "shipped"
        assert db.get(Package, run["package_ids"][0]).status == "shipped"
        assert db.query(Invoice).filter_by(id=inv.id).one().amount == 14
