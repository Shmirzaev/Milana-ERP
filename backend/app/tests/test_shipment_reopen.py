from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.session import SessionLocal
from app.models import AuditLog, FinishedGoodsStock, Invoice, Package, Payment, SalesOrder, Shipment
from app.services.payments import create_invoice_payment
from app.services.finance_1c import sync_from_1c
from app.schemas.integrations import OneCSyncIn
from app.tests.test_manual_pack_dispatch import receive, shipment
from app.tests.test_package_workflows import warehouse, package_qr  # noqa: F401
from app.tests.test_shipment_review import dispatch  # noqa: F401


def payload(result):
    return {"reason": "All goods returned for correction", "packages_returned": True,
            "expected_shipped_at": result["shipped_at"]}


@pytest.mark.parametrize("price,delivered", [(None, False), (None, True), (Decimal("2.5"), False), (Decimal("2.5"), True)])
def test_manual_return_and_redispatch(client, warehouse, price, delivered):
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
    body = payload(shipped.json())
    result = client.post(url + "/reopen", headers=warehouse, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "created" and result.json()["shipment_type"] == "manual"
    assert result.json()["shipped_at"] is None and result.json()["delivered_at"] is None
    assert result.json()["scanned_count"] == 0 and result.json()["packages_count"] == 2
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.id.in_(ids)).all()
        assert sum(s.available_qty for s in stocks) == 30 and sum(s.sold_qty for s in stocks) == 0
        assert all(db.get(Package, pid).status == "received_in_storage" for pid in run["package_ids"])
        assert db.get(Shipment, sid).sales_order_id is None
        evidence = db.query(AuditLog).filter_by(action="reopen_shipment", entity_id=sid).one()
        assert evidence.old_value_json["dispatch_snapshot"]["document"]["quantity"] == 30
        if old_order:
            invoice = db.query(Invoice).filter_by(sales_order_id=old_order).one()
            assert invoice.status == "void" and invoice.amount == 0
            assert db.get(SalesOrder, old_order).total_amount == 0
            with pytest.raises(HTTPException):
                create_invoice_payment(db, invoice, amount=1)
            synced = sync_from_1c(db, OneCSyncIn(
                invoices=[{"external_id": "late-invoice", "sales_order_id": old_order, "amount": 75}],
                payments=[{"external_id": "late-payment", "invoice_id": invoice.id, "amount": 1}],
            ))
            assert len(synced["errors"]) == 2 and synced["payments_created"] == 0 and synced["invoices_created"] == 0
    assert client.post(url + "/reopen", headers=warehouse, json=body).status_code == 409
    assert client.post(url + "/ship", headers={**warehouse, "Idempotency-Key": "first-dispatch"}).status_code == 409
    assert client.post(url + "/ship", headers=warehouse).status_code == 409
    for pid in run["package_ids"]:
        assert client.post(url + "/scan-package", headers={**warehouse, "Idempotency-Key": f"scan-{pid}"}, json={"code": package_qr(pid)}).status_code == 409
        result = client.post(url + "/scan-package", headers=warehouse, json={"code": package_qr(pid)})
        assert result.json()["ok"], result.text
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
    assert client.post(url + "/scan-package", headers=auth_headers, json={"code": "REVIEW-QR"}).json()["ok"]
    assert client.post(url + "/ship", headers=auth_headers).status_code == 200
    result = client.post(url + "/deliver", headers=auth_headers)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        invoices = db.query(Invoice).filter_by(sales_order_id=dispatch["order"]).all()
        assert len(invoices) == 2 and sum(i.amount for i in invoices) == 80


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
