from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    FinishedGoodsStock, LegacyStockReceipt, ManualPackageReceipt, Model, Package,
    PackageItem, SalesOrder, Shipment, ShipmentPackage, StockReservation, User,
)


def _stock(source="manual", quantities=(4, 6)):
    with SessionLocal() as db:
        token = uuid4().hex[:10]
        user = db.query(User).filter_by(email="admin@example.com").one()
        model = Model(code=f"MFG-{token}", name="Manual finished goods", status="approved")
        order = SalesOrder(order_no=f"MFG-{token}", order_type="branded_stock_sale", status="draft")
        db.add_all([model, order])
        db.flush()
        package = None
        if source != "aggregate":
            if source == "manual":
                receipt = ManualPackageReceipt(receipt_no=f"MFG-{token}", created_by=user.id,
                                               evidence={"quantities": list(quantities)}, evidence_hash="a" * 64)
            else:
                receipt = LegacyStockReceipt(source_system="TEST", source_warehouse_id="test",
                                             source_record_id=token, source_checksum="a" * 64,
                                             source_payload={"test": True})
            db.add(receipt)
            db.flush()
            package = Package(package_no=f"MFG-{token}", barcode=f"MFG-{token}", model_id=model.id,
                              color="blue", total_quantity=sum(quantities), capacity=sum(quantities),
                              status="received_in_storage",
                              **{f"{source}_receipt_id": receipt.id})
            db.add(package)
            db.flush()
        rows = []
        for size, quantity in enumerate(quantities):
            if package:
                db.add(PackageItem(package_id=package.id, model_id=model.id, color="blue",
                                   size=str(size), quantity=quantity))
            stock = FinishedGoodsStock(package_id=package.id if package else None, model_id=model.id,
                                       color="blue", size=str(size), quantity=quantity,
                                       available_qty=quantity, status="available")
            db.add(stock)
            rows.append(stock)
        db.commit()
        return {"package_id": package.id if package else None, "stock_ids": [row.id for row in rows],
                "sales_order_id": order.id, "user_id": user.id}


def _reserve(client, headers, fixture, quantity):
    return client.post("/api/finished-goods/reserve", headers=headers,
                       params={"stock_id": fixture["stock_ids"][0], "quantity": quantity,
                               "sales_order_id": fixture["sales_order_id"]})


def _balances(fixture):
    with SessionLocal() as db:
        stocks = [(s.id, s.quantity, s.available_qty, s.reserved_qty, s.sold_qty, s.status)
                  for s in db.query(FinishedGoodsStock).filter(
                      FinishedGoodsStock.id.in_(fixture["stock_ids"])).order_by(FinishedGoodsStock.id)]
        reservations = [(r.id, r.finished_goods_stock_id, r.quantity) for r in db.query(StockReservation).filter(
            StockReservation.finished_goods_stock_id.in_(fixture["stock_ids"])).order_by(StockReservation.id)]
        return stocks, reservations


def test_manual_multisize_pack_reserves_all_rows_and_rejects_retry(client, auth_headers):
    fixture = _stock()
    response = _reserve(client, auth_headers, fixture, 10)
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 10
    stocks, reservations = _balances(fixture)
    assert [(s[1], s[2], s[3], s[4], s[5]) for s in stocks] == [
        (4, 0, 4, 0, "reserved"), (6, 0, 6, 0, "reserved")]
    assert sum(r[2] for r in reservations) == 10
    assert len(reservations) == 2
    assert _reserve(client, auth_headers, fixture, 10).status_code == 409
    assert _balances(fixture) == (stocks, reservations)
    with SessionLocal() as db:
        package = db.get(Package, fixture["package_id"])
        assert package.total_quantity == 10
        assert db.get(ManualPackageReceipt, package.manual_receipt_id).evidence == {"quantities": [4, 6]}


@pytest.mark.parametrize("quantity", [1, 4, 9, 11])
def test_manual_partial_or_excess_reservation_is_atomic(client, auth_headers, quantity):
    fixture = _stock()
    before = _balances(fixture)
    assert _reserve(client, auth_headers, fixture, quantity).status_code == 409
    assert _balances(fixture) == before


@pytest.mark.parametrize("invalid", ["packed", "damaged", "shipped", "partial", "sold", "stock_status",
                                    "wrong_size", "wrong_total", "missing_item", "reservation", "shipment",
                                    "closed_order", "missing_order"])
def test_manual_reserve_rejects_unavailable_or_unbalanced_package(client, auth_headers, invalid):
    fixture = _stock()
    with SessionLocal() as db:
        package = db.get(Package, fixture["package_id"])
        stock = db.get(FinishedGoodsStock, fixture["stock_ids"][1])
        if invalid in {"packed", "damaged", "shipped"}:
            package.status = invalid
        elif invalid == "partial":
            stock.available_qty -= 1
            stock.reserved_qty = 1
        elif invalid == "sold":
            stock.available_qty -= 1
            stock.sold_qty = 1
        elif invalid == "stock_status":
            stock.status = "damaged"
        elif invalid == "wrong_size":
            stock.size = "unmatched"
        elif invalid == "wrong_total":
            package.total_quantity = 11
        elif invalid == "missing_item":
            db.query(PackageItem).filter_by(package_id=package.id).delete()
        elif invalid == "reservation":
            # Even a historical row missing package_id must prevent reuse.
            db.add(StockReservation(sales_order_id=fixture["sales_order_id"],
                                    finished_goods_stock_id=stock.id, quantity=1,
                                    reserved_by=fixture["user_id"]))
        elif invalid == "shipment":
            shipment = Shipment(shipment_no=f"MFG-{uuid4().hex[:10]}", status="draft")
            db.add(shipment)
            db.flush()
            db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=10))
        elif invalid == "closed_order":
            db.get(SalesOrder, fixture["sales_order_id"]).status = "closed"
        elif invalid == "missing_order":
            db.delete(db.get(SalesOrder, fixture["sales_order_id"]))
        db.commit()
    before = _balances(fixture)
    response = _reserve(client, auth_headers, fixture, 11 if invalid == "wrong_total" else 10)
    assert response.status_code == (404 if invalid == "missing_order" else 409), response.text
    assert _balances(fixture) == before


@pytest.mark.parametrize("source", ["legacy", "aggregate"])
def test_nonmanual_piece_reservation_remains_unchanged(client, auth_headers, source):
    fixture = _stock(source)
    response = _reserve(client, auth_headers, fixture, 2)
    assert response.status_code == 200, response.text
    stocks, reservations = _balances(fixture)
    assert stocks[0][2:4] == (2, 2)
    assert stocks[1][2:4] == (6, 0)
    assert [r[2] for r in reservations] == [2]


def test_unbranded_manual_stock_is_listed_and_reserved_rows_disappear(client, auth_headers):
    fixture = _stock()
    def listed():
        response = client.get("/api/finished-goods/branded-stock", headers=auth_headers)
        assert response.status_code == 200, response.text
        return {r["id"]: r for r in response.json()}
    rows = listed()
    assert set(fixture["stock_ids"]).issubset(rows)
    assert all(rows[sid]["brand_id"] is None for sid in fixture["stock_ids"])
    assert _reserve(client, auth_headers, fixture, 10).status_code == 200
    assert not set(fixture["stock_ids"]).intersection(listed())


def test_manual_reserve_requests_refreshing_package_then_stock_locks(client, auth_headers):
    fixture = _stock()
    locks = []
    def capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                locks.append((sql, state.load_options._populate_existing))
    event.listen(Session, "do_orm_execute", capture)
    try:
        response = _reserve(client, auth_headers, fixture, 10)
    finally:
        event.remove(Session, "do_orm_execute", capture)
    assert response.status_code == 200, response.text
    package_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF packages" in sql)
    stock_lock = next(i for i, (sql, _) in enumerate(locks) if "FOR UPDATE OF finished_goods_stock" in sql)
    assert package_lock < stock_lock
    assert locks[package_lock][1] and locks[stock_lock][1]


def _release(client, headers, reservation_id):
    return client.post("/api/finished-goods/release-reservation", headers=headers,
                       params={"reservation_id": reservation_id})


def test_manual_release_restores_whole_multisize_package_with_ordered_locks(client, auth_headers):
    fixture = _stock()
    assert _reserve(client, auth_headers, fixture, 10).status_code == 200
    reservation_ids = [r[0] for r in _balances(fixture)[1]]
    locks = []
    def capture(state):
        if state.is_select:
            sql = str(state.statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                locks.append((sql, state.load_options._populate_existing))
    event.listen(Session, "do_orm_execute", capture)
    try:
        response = _release(client, auth_headers, reservation_ids[1])
    finally:
        event.remove(Session, "do_orm_execute", capture)
    assert response.status_code == 200, response.text
    assert response.json()["quantity"] == 10
    stocks, reservations = _balances(fixture)
    assert [(s[2], s[3], s[4]) for s in stocks] == [(4, 0, 0), (6, 0, 0)]
    assert not reservations
    assert _release(client, auth_headers, reservation_ids[0]).status_code == 404
    assert _balances(fixture) == (stocks, reservations)
    indices = [next(i for i, (sql, _) in enumerate(locks) if f"FOR UPDATE OF {table}" in sql)
               for table in ("packages", "finished_goods_stock", "stock_reservations")]
    assert indices == sorted(indices)
    assert all(locks[i][1] for i in indices)


@pytest.mark.parametrize("invalid", ["shipped", "delivered", "damaged", "sold", "partial",
                                    "reservation_balance", "different_order"])
def test_manual_release_rejects_sold_partial_or_misowned_stock_atomically(client, auth_headers, invalid):
    fixture = _stock()
    assert _reserve(client, auth_headers, fixture, 10).status_code == 200
    with SessionLocal() as db:
        package = db.get(Package, fixture["package_id"])
        stock = db.get(FinishedGoodsStock, fixture["stock_ids"][1])
        reservations = db.query(StockReservation).filter_by(package_id=package.id).order_by(StockReservation.id).all()
        reservation_id = reservations[0].id
        if invalid in {"shipped", "delivered", "damaged"}:
            package.status = invalid
        elif invalid == "sold":
            stock.sold_qty, stock.reserved_qty = 1, stock.quantity - 1
        elif invalid == "partial":
            stock.available_qty, stock.reserved_qty = 1, stock.quantity - 1
        elif invalid == "reservation_balance":
            reservations[1].quantity -= 1
        else:
            order = SalesOrder(order_no=f"MFG-{uuid4().hex[:10]}", status="draft")
            db.add(order)
            db.flush()
            reservations[1].sales_order_id = order.id
        db.commit()
    before = _balances(fixture)
    response = _release(client, auth_headers, reservation_id)
    assert response.status_code == 409, response.text
    assert _balances(fixture) == before


@pytest.mark.parametrize("status", ["draft", "created", "shipped", "delivered", "cancelled"])
def test_manual_release_blocks_active_shipment_attachments(client, auth_headers, status):
    fixture = _stock()
    assert _reserve(client, auth_headers, fixture, 10).status_code == 200
    before = _balances(fixture)
    with SessionLocal() as db:
        shipment = Shipment(shipment_no=f"MFG-{uuid4().hex[:10]}", status=status)
        db.add(shipment)
        db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=fixture["package_id"], quantity=10))
        db.commit()
    response = _release(client, auth_headers, before[1][0][0])
    assert response.status_code == (200 if status == "cancelled" else 409), response.text
    if status != "cancelled":
        assert _balances(fixture) == before


def test_manual_release_resolves_missing_reservation_package_link(client, auth_headers):
    fixture = _stock()
    assert _reserve(client, auth_headers, fixture, 10).status_code == 200
    with SessionLocal() as db:
        rows = db.query(StockReservation).filter_by(package_id=fixture["package_id"]).all()
        reservation_id = rows[0].id
        for row in rows:
            row.package_id = None
        db.commit()
    assert _release(client, auth_headers, reservation_id).status_code == 200
    assert not _balances(fixture)[1]
    assert sum(row[2] for row in _balances(fixture)[0]) == 10


def test_dispatched_manual_pack_reservation_release_cannot_recreate_available_stock(client, auth_headers):
    fixture = _stock()
    with SessionLocal() as db:
        package = db.get(Package, fixture["package_id"])
        model_id, barcode = package.model_id, package.barcode
    sale = client.post("/api/sales-orders", headers=auth_headers, json={
        "order_type": "branded_stock_sale", "items": [{"model_id": model_id, "requested_pack_count": 1,
                                                     "color": "mixed", "size": "any", "unit_price": 2}],
    })
    assert sale.status_code == 201, sale.text
    shipment = client.post("/api/shipments", headers=auth_headers, json={"sales_order_id": sale.json()["id"]})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    scan = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": barcode})
    assert scan.status_code == 200 and scan.json()["ok"], scan.text
    dispatched = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert dispatched.status_code == 200, dispatched.text
    before = _balances(fixture)
    assert sum(row[4] for row in before[0]) == 10
    assert sum(row[2] + row[3] for row in before[0]) == 0
    assert before[1], "Dispatch retains historical reservation rows"
    for reservation in before[1]:
        assert _release(client, auth_headers, reservation[0]).status_code == 409
    assert _balances(fixture) == before


@pytest.mark.parametrize("source", ["legacy", "aggregate"])
def test_nonmanual_release_remains_piece_based(client, auth_headers, source):
    fixture = _stock(source)
    assert _reserve(client, auth_headers, fixture, 2).status_code == 200
    reservation_id = _balances(fixture)[1][0][0]
    assert _release(client, auth_headers, reservation_id).status_code == 200
    stocks, reservations = _balances(fixture)
    assert [(s[2], s[3]) for s in stocks] == [(4, 0), (6, 0)]
    assert not reservations
