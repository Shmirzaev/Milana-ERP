from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql

from app.db.session import SessionLocal
from app.models import (
    Brand, FinishedGoodsStock, LegacyStockReceipt, Model, Package, PackageItem,
    SalesOrder, Shipment, ShipmentPackage, StockReservation,
)
from app.services.ready_stock_sales import ready_pack_candidates


def _packs(quantities=(60, 78, 12)):
    with SessionLocal() as db:
        suffix = uuid4().hex[:8]
        model = Model(code=f"PACK-SALE-{suffix}", name="Pack sales test", status="approved", selling_price=2)
        db.add(model)
        db.flush()
        ids = []
        for index, quantity in enumerate(quantities):
            receipt = LegacyStockReceipt(
                source_system="TEST", source_warehouse_id="test", source_record_id=f"{suffix}-{index}",
                source_checksum="0" * 64, source_payload={"test": True},
            )
            db.add(receipt)
            db.flush()
            package = Package(
                package_no=f"PS-{suffix}-{index}", barcode=f"PS-{suffix}-{index}",
                legacy_receipt_id=receipt.id, model_id=model.id, color="mixed",
                total_quantity=quantity, capacity=60, status="received_in_storage",
            )
            db.add(package)
            db.flush()
            for size, qty in (("46", quantity // 2), ("48", quantity - quantity // 2)):
                db.add(PackageItem(package_id=package.id, model_id=model.id, color="white", size=size, quantity=qty))
                db.add(FinishedGoodsStock(
                    package_id=package.id, model_id=model.id, color="white", size=size,
                    quantity=qty, available_qty=qty, reserved_qty=0, sold_qty=0, status="available",
                ))
            ids.append(package.id)
        db.commit()
        return model.id, ids


def _payload(model_id, count=1, **overrides):
    return {"order_type": "branded_stock_sale", "items": [{
        "model_id": model_id, "color": "mixed", "size": "any", "requested_pack_count": count, **overrides,
    }]}


def test_ready_sales_reserves_exact_pack_count_and_real_mixed_size_totals(client, auth_headers):
    model_id, package_ids = _packs()
    options = client.get("/api/sales-orders/ready-stock-options", headers=auth_headers)
    assert options.status_code == 200, options.text
    assert next(row for row in options.json() if row["model_id"] == model_id) == {
        "model_id": model_id, "brand_id": None, "pack_count": 3, "quantity": 150,
    }
    response = client.post("/api/sales-orders", json=_payload(model_id, 2), headers=auth_headers)
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["items"][0]["requested_pack_count"] == 2
    assert order["items"][0]["quantity"] == 138
    assert order["total_amount"] == 276
    assert order["status"] == "ready"
    with SessionLocal() as db:
        reservations = db.query(StockReservation).filter(StockReservation.sales_order_id == order["id"]).all()
        assert {row.package_id for row in reservations} == set(package_ids[:2])
        assert sum(row.quantity for row in reservations) == 138
        for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(package_ids)):
            assert row.quantity == row.available_qty + row.reserved_qty + row.sold_qty
            assert row.reserved_qty in (0, row.quantity)
    repeat = client.post(f"/api/sales-orders/{order['id']}/reserve-stock", headers=auth_headers)
    assert repeat.status_code == 409
    second = client.post("/api/sales-orders", json=_payload(model_id), headers=auth_headers)
    assert second.status_code == 201, second.text
    assert second.json()["items"][0]["quantity"] == 12
    detail = client.get(f"/api/sales-orders/{order['id']}", headers=auth_headers)
    assert detail.json()["items"][0]["requested_pack_count"] == 2


@pytest.mark.parametrize("count", [0, -1, 1.5, "2", True])
def test_ready_sales_rejects_invalid_pack_count(client, auth_headers, count):
    model_id, _ = _packs()
    response = client.post("/api/sales-orders", json=_payload(model_id, count), headers=auth_headers)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("change", ["quantity", "printing", "duplicate", "production", "missing_count"])
def test_ready_sales_rejects_ambiguous_or_client_piece_inputs(client, auth_headers, change):
    model_id, _ = _packs()
    payload = _payload(model_id)
    line = payload["items"][0]
    if change == "quantity":
        line["quantity"] = 999
    elif change == "printing":
        line["printing_required"] = True
    elif change == "duplicate":
        payload["items"].append(dict(line))
    elif change == "production":
        payload["order_type"] = "client_order"
    else:
        payload["items"].append({"model_id": model_id, "color": "white", "size": "46", "quantity": 1})
    response = client.post("/api/sales-orders", json=payload, headers=auth_headers)
    assert response.status_code == 400, response.text
    with SessionLocal() as db:
        assert db.query(StockReservation).count() == 0


@pytest.mark.parametrize("invalid", ["packed", "damaged", "partial", "missing_item", "wrong_size", "duplicate_stock", "order_owned", "reserved_record", "attached"])
def test_ready_sales_excludes_nonwhole_or_unbalanced_packages(client, auth_headers, invalid):
    model_id, ids = _packs((60,))
    with SessionLocal() as db:
        package = db.get(Package, ids[0])
        stock = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == ids[0]).first()
        if invalid in ("packed", "damaged"):
            package.status = invalid
        elif invalid == "partial":
            stock.available_qty -= 1
            stock.sold_qty += 1
        elif invalid == "missing_item":
            db.query(PackageItem).filter(PackageItem.package_id == ids[0]).delete()
        elif invalid == "wrong_size":
            stock.size = "50"
        elif invalid == "duplicate_stock":
            db.add(FinishedGoodsStock(
                package_id=package.id, model_id=model_id, color="white", size="46",
                quantity=30, available_qty=30, reserved_qty=0, sold_qty=0, status="available",
            ))
        else:
            order = SalesOrder(order_no=f"OWNER-{uuid4().hex[:8]}")
            db.add(order)
            db.flush()
            if invalid == "order_owned":
                package.sales_order_id = order.id
            elif invalid == "reserved_record":
                db.add(StockReservation(sales_order_id=order.id, finished_goods_stock_id=stock.id, package_id=package.id, quantity=1))
            else:
                shipment = Shipment(shipment_no=f"ATTACHED-{uuid4().hex[:8]}", sales_order_id=order.id)
                db.add(shipment)
                db.flush()
                db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=package.total_quantity))
        db.commit()
    response = client.get("/api/sales-orders/ready-stock-options", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert not any(row["model_id"] == model_id for row in response.json())
    response = client.post("/api/sales-orders", json=_payload(model_id), headers=auth_headers)
    assert response.status_code == 409, response.text


def test_ready_sales_shortage_is_atomic_and_aggregate_stock_is_not_a_pack(client, auth_headers):
    model_id, _ = _packs((60,))
    with SessionLocal() as db:
        db.add(FinishedGoodsStock(model_id=model_id, color="white", size="46", quantity=999, available_qty=999))
        db.commit()
        order_count = db.query(SalesOrder).count()
    response = client.post("/api/sales-orders", json=_payload(model_id, 2), headers=auth_headers)
    assert response.status_code == 409, response.text
    with SessionLocal() as db:
        assert db.query(SalesOrder).count() == order_count
        assert db.query(StockReservation).count() == 0
        assert sum(row.reserved_qty for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.model_id == model_id)) == 0


def test_ready_sales_options_permissions_and_bounded_queries(client, auth_headers):
    model_id, _ = _packs(tuple([12] * 25))
    statements = []
    with SessionLocal() as db:
        bind = db.get_bind()
    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(bind, "before_cursor_execute", capture)
    try:
        response = client.get("/api/sales-orders/ready-stock-options", headers=auth_headers)
    finally:
        event.remove(bind, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert next(row for row in response.json() if row["model_id"] == model_id)["pack_count"] == 25
    assert len(statements) <= 12
    assert client.get("/api/sales-orders/ready-stock-options").status_code == 401
    login = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/sales-orders/ready-stock-options", headers=headers).status_code == 403
    assert client.post("/api/sales-orders", json=_payload(model_id), headers=headers).status_code == 403


def test_regular_production_sales_keep_piece_quantity(client, auth_headers):
    model_id, _ = _packs()
    payload = {"order_type": "client_order", "items": [{
        "model_id": model_id, "color": "black", "size": "50", "quantity": 7, "printing_required": True,
    }]}
    response = client.post("/api/sales-orders", json=payload, headers=auth_headers)
    assert response.status_code == 201, response.text
    line = response.json()["items"][0]
    assert line["requested_pack_count"] is None
    assert (line["quantity"], line["color"], line["size"], line["printing_required"]) == (7, "black", "50", True)
    assert response.json()["total_amount"] == 14
    with SessionLocal() as db:
        assert db.query(StockReservation).count() == 0


def test_ready_sales_brand_filter_never_splits_or_borrows_another_brands_pack(client, auth_headers):
    model_id, ids = _packs((60, 78))
    with SessionLocal() as db:
        brands = [Brand(name=f"Pack brand {uuid4().hex[:8]}") for _ in range(2)]
        db.add_all(brands)
        db.flush()
        for index, package_id in enumerate(ids):
            db.get(Package, package_id).brand_id = brands[index].id
            for stock in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id == package_id):
                stock.brand_id = brands[index].id
        db.commit()
        brand_id = brands[0].id
    response = client.post("/api/sales-orders", json=_payload(model_id, 2, brand_id=brand_id), headers=auth_headers)
    assert response.status_code == 409, response.text
    response = client.post("/api/sales-orders", json=_payload(model_id, 1, brand_id=brand_id), headers=auth_headers)
    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["quantity"] == 60
    with SessionLocal() as db:
        assert {row.package_id for row in db.query(StockReservation).all()} == {ids[0]}


def test_ready_sales_locks_packages_before_stock_and_excludes_attached_candidates(monkeypatch):
    model_id, ids = _packs((60, 78))
    with SessionLocal() as db:
        shipment = Shipment(shipment_no=f"LOCK-{uuid4().hex[:8]}")
        db.add(shipment)
        db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=ids[0], quantity=60))
        db.commit()
        statements = []

        def capture(state):
            statements.append(str(state.statement.compile(dialect=postgresql.dialect())))

        event.listen(db, "do_orm_execute", capture)
        # Exercise the PostgreSQL lock branches against the isolated SQLite
        # fixture; separately compile their statements with the PG dialect.
        monkeypatch.setattr(db.get_bind().dialect, "name", "postgresql")
        candidates = ready_pack_candidates(db, model_ids={model_id}, lock=True)
        assert [package.id for package, _ in candidates] == [ids[1]]
        locked = [statement for statement in statements if "FOR UPDATE" in statement]
        assert len(locked) == 2
        assert "ORDER BY packages.id FOR UPDATE OF packages" in locked[0]
        assert "NOT (EXISTS" in locked[0] and "shipment_packages" in locked[0]
        assert "ORDER BY finished_goods_stock.id FOR UPDATE OF finished_goods_stock" in locked[1]
