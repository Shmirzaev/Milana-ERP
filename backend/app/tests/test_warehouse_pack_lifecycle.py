"""Receipt -> partial dispatch -> same-label remainder and guarded deletion."""
import pytest

from app.db.session import SessionLocal
from app.models import (FinishedGoodsStock, Package, PackageItem, PackagePrintRun, PackagePrintRunMember,
                        SalesOrderItem, ShipmentPackage, StockReservation)
from app.tests.test_shipment_review import dispatch, preparation  # noqa: F401
from app.tests.test_package_workflows import packaging_order, warehouse, create_run, stock_fingerprint  # noqa: F401


def test_sixty_ship_thirty_same_qr_then_ship_remaining(client, auth_headers, dispatch):
    with SessionLocal() as db:
        package = db.get(Package, dispatch["package"])
        package.total_quantity = 60
        for row in db.query(PackageItem).filter_by(package_id=package.id):
            row.quantity = 30
        for stock in db.query(FinishedGoodsStock).filter_by(package_id=package.id):
            stock.quantity = stock.reserved_qty = 30
        for reservation in db.query(StockReservation).filter_by(package_id=package.id):
            reservation.quantity = 30
        db.query(ShipmentPackage).filter_by(package_id=package.id).one().quantity = 60
        db.query(SalesOrderItem).filter_by(sales_order_id=dispatch["order"]).one().quantity = 60
        db.commit()
    response = client.post(f'/api/shipments/{dispatch["shipment"]}/packages/{dispatch["package"]}/quantity', headers=auth_headers,
                           json={"expected_quantity": 60, "keep_remainder": True, "reason": "Ship half now",
                                 "items": [{"item_id": item, "quantity": 15} for item in dispatch["items"]]})
    assert response.status_code == 200, response.text
    assert response.json()["review"]["quantity"] == 30
    assert response.json()["review"]["amount"] == "300.00"
    with SessionLocal() as db:
        assert sum(s.available_qty + s.reserved_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"])) == 60
    response = client.post(f'/api/shipments/{dispatch["shipment"]}/ship', headers=auth_headers)
    assert response.status_code == 200, response.text
    qr = client.get('/api/packages/barcode/REVIEW-QR', headers=auth_headers)
    assert qr.status_code == 200, qr.text
    assert qr.json()["total_quantity"] == 30
    assert sum(i["quantity"] for i in qr.json()["items"]) == 30
    assert qr.json()["barcode"] == "REVIEW-QR" and qr.json()["status"] == "received_in_storage"
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"]).all()
        assert sum(s.available_qty for s in stocks) == sum(s.sold_qty for s in stocks) == 30
        assert sum(s.reserved_qty for s in stocks) == 0
        assert db.get(Package, dispatch["package"]).quantity_shortfall == 0
        assert not db.query(StockReservation).filter_by(package_id=dispatch["package"]).count()
    invoice = client.get(f'/api/shipments/{dispatch["shipment"]}/invoice', headers=auth_headers).json()
    assert sum(line["quantity"] for line in invoice["lines"]) == 30
    assert client.delete(f'/api/packages/warehouse/{dispatch["package"]}', headers=auth_headers).status_code == 409
    second = client.post('/api/shipments', headers=auth_headers, json={"notes": "Remaining physical pack"})
    assert second.status_code == 201, second.text
    sid = second.json()["id"]
    scan = client.post(f'/api/shipments/{sid}/scan-package', headers=auth_headers, json={"code": "REVIEW-QR"})
    assert scan.status_code == 200, scan.text
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=sid).one().quantity == 30
    result = client.post(f'/api/shipments/{sid}/ship', headers=auth_headers)
    assert result.status_code == 200, result.text
    history = client.get(f'/api/shipments/{sid}/preparation', headers=auth_headers)
    assert history.status_code == 200, history.text
    assert sum(item['quantity'] for package in history.json()['packages'] for item in package['items']) == 30
    with SessionLocal() as db:
        assert db.get(Package, dispatch["package"]).status == "shipped"
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"])) == 60
    assert client.get(f'/api/shipments/{dispatch["shipment"]}/invoice', headers=auth_headers).json() == invoice
    first_delivery = client.post(f'/api/shipments/{dispatch["shipment"]}/deliver', headers=auth_headers)
    assert first_delivery.status_code == 200, first_delivery.text
    with SessionLocal() as db:
        assert db.get(Package, dispatch["package"]).status == "shipped"
    assert client.post(f'/api/shipments/{sid}/deliver', headers=auth_headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Package, dispatch["package"]).status == "delivered"


@pytest.mark.parametrize("quantities,expected", [([5,4],8), ([0,0],8), ([3,4],7)])
def test_selection_rejects_overdraw_zero_and_stale(client, auth_headers, dispatch, quantities, expected):
    before = stock_fingerprint()
    result = client.post(f'/api/shipments/{dispatch["shipment"]}/packages/{dispatch["package"]}/quantity', headers=auth_headers,
                         json={"expected_quantity": expected, "keep_remainder": True, "reason": "Partial shipment",
                               "items": [{"item_id": item, "quantity": qty} for item, qty in zip(dispatch["items"], quantities)]})
    assert result.status_code == 409, result.text
    assert stock_fingerprint() == before


def test_receive_by_order_and_delete_one_pack(client, auth_headers, warehouse, packaging_order):
    run = create_run(client, auth_headers, packaging_order, 2)
    ids = run["package_ids"]
    options = client.get('/api/packages/receiving-orders?q=PO-PRINT', headers=warehouse)
    assert options.status_code == 200, options.text
    row = options.json()["rows"][0]
    assert row["package_ids"] == ids
    before = stock_fingerprint()
    url = f'/api/packages/receive-order/{row["id"]}'
    assert client.post(url, headers=warehouse, json={"package_ids": ids[:1]}).status_code == 409
    received = client.post(url, headers=warehouse, json={"package_ids": ids})
    assert received.status_code == 200, received.text
    assert client.post(url, headers=warehouse, json={"package_ids": ids}).status_code == 200
    assert stock_fingerprint() == before
    assert client.get('/api/packages/receiving-orders?q=PO-PRINT', headers=warehouse).json()["rows"] == []
    deleted = client.delete(f'/api/packages/warehouse/{ids[0]}', headers=warehouse)
    assert deleted.status_code == 200, deleted.text
    with SessionLocal() as db:
        assert db.get(Package, ids[0]) is None
        assert db.get(Package, ids[1]).status == "received_in_storage"
        assert db.query(PackagePrintRunMember).filter_by(run_id=run["id"]).count() == 2
        assert db.get(PackagePrintRun, run["id"]).deleted_package_ids == [ids[0]]


def test_warehouse_actions_require_warehouse_permission(client, auth_headers, packaging_order):
    from app.tests.test_payroll import _create_user_with_permissions
    headers = _create_user_with_permissions(client, auth_headers, email="packaging-only-lifecycle@example.com", permissions=["packaging.packages"])
    run = create_run(client, auth_headers, packaging_order, 1)
    pid = run["package_ids"][0]
    assert client.delete(f'/api/packages/warehouse/{pid}', headers=headers).status_code == 403
    assert client.get('/api/packages/receiving-orders', headers=headers).status_code == 403
    assert client.post('/api/packages/receive-order/1', headers=headers, json={"package_ids": [pid]}).status_code == 403


def test_manual_partial_invoice_reopen_and_reserve_remainder(client, warehouse, auth_headers):
    from app.tests.test_manual_pack_dispatch import receive, shipment
    from app.tests.test_package_workflows import package_qr
    from app.models import Shipment, Customer
    from app.tests.test_shipment_reopen import payload
    run = receive(client, warehouse, (60,))
    pid = run["package_ids"][0]
    sid = shipment(client, warehouse, 2)
    url = f'/api/shipments/{sid}'
    assert client.post(url + '/scan-package', headers=warehouse, json={"code": package_qr(pid)}).json()["ok"]
    item = client.get(url + '/preparation', headers=warehouse).json()["packages"][0]["quantity_items"][0]
    result = client.post(url + f'/packages/{pid}/quantity', headers=warehouse,
                         json={"keep_remainder": True, "expected_quantity": 60, "reason": "Half shipment",
                               "items": [{"item_id": item["item_id"], "quantity": 30}]})
    assert result.status_code == 200, result.text
    shipped = client.post(url + '/ship', headers=warehouse)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        order_id = db.get(Shipment, sid).sales_order_id
        assert sum(row.quantity for row in db.query(SalesOrderItem).filter_by(sales_order_id=order_id)) == 30
        customer_id = db.query(Customer).first().id
    reopened = client.post(url + '/reopen', headers=warehouse, json=payload(shipped.json()))
    assert reopened.status_code == 200, reopened.text
    assert client.get(f'/api/packages/{pid}', headers=warehouse).json()["total_quantity"] == 60
    shipped = client.post(url + '/ship', headers=warehouse)
    assert shipped.status_code == 200, shipped.text
    assert client.get(f'/api/packages/{pid}', headers=warehouse).json()["total_quantity"] == 30
    available = client.get('/api/warehouse-reservations?reserved=false', headers=warehouse).json()
    assert next(row for row in available["rows"] if row["id"] == pid)["quantity"] == 30
    reserve = client.post('/api/warehouse-reservations', headers=warehouse, json={"package_ids": [pid], "customer_id": customer_id})
    assert reserve.status_code == 200, reserve.text
    assert client.delete(f'/api/packages/warehouse/{pid}', headers=warehouse).status_code == 409
    released = client.post('/api/warehouse-reservations/release', headers=warehouse, json={"package_ids": [pid]})
    assert released.status_code == 200, released.text
    with SessionLocal() as db:
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert stock.available_qty == stock.sold_qty == 30 and stock.reserved_qty == 0
        from app.models import SalesOrder
        order = SalesOrder(order_no="SO-PARTIAL-RESERVE", customer_id=customer_id, status="draft", total_amount=60)
        db.add(order); db.commit()
        oid, stock_id = order.id, stock.id
    reserved = client.post('/api/finished-goods/reserve', headers=auth_headers,
                           params={"stock_id": stock_id, "quantity": 30, "sales_order_id": oid})
    assert reserved.status_code == 200, reserved.text
    with SessionLocal() as db:
        rid = db.query(StockReservation).filter_by(package_id=pid).one().id
    released = client.post('/api/finished-goods/release-reservation', headers=auth_headers, params={"reservation_id": rid})
    assert released.status_code == 200, released.text
    with SessionLocal() as db:
        stock = db.get(FinishedGoodsStock, stock_id)
        assert stock.available_qty == stock.sold_qty == 30 and stock.reserved_qty == 0


@pytest.mark.parametrize("condition", ["reserved", "shipment", "stock"])
def test_delete_rejects_linked_or_changed_packs(client, warehouse, condition):
    from app.tests.test_manual_pack_dispatch import receive
    from app.models import Shipment
    pid = receive(client, warehouse, (60,))["package_ids"][0]
    with SessionLocal() as db:
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        if condition == "reserved":
            stock.reserved_qty = 1
            stock.available_qty -= 1
        elif condition == "shipment":
            shipment = Shipment(shipment_no="SH-DELETE-GUARD", status="created")
            db.add(shipment); db.flush()
            db.add(ShipmentPackage(shipment_id=shipment.id, package_id=pid, quantity=60))
        else:
            stock.available_qty -= 1
        db.commit()
    before = stock_fingerprint()
    result = client.delete(f'/api/packages/warehouse/{pid}', headers=warehouse)
    assert result.status_code == 409, result.text
    assert stock_fingerprint() == before
    with SessionLocal() as db:
        assert db.get(Package, pid)
