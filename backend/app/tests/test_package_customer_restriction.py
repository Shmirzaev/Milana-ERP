"""Customer-bound pack scanning and explicit administrator release regressions."""
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.schemas import (
    AuditLog, Customer, Department, FinishedGoodsStock, Model, Package, PackageItem,
    ProductionOrder, SalesOrder, SalesOrderItem, Shipment, ShipmentPackage,
    ShipmentScanLog, StockMovement, StockReservation, User, WarehousePackReservation,
)


@pytest.fixture
def customer_packs():
    marker = uuid4().hex[:10]
    with SessionLocal() as db:
        model = Model(code=f"CUSTOMER-{marker}", name="Customer restriction test", status="approved")
        customers = [Customer(name=f"Customer {letter} {marker}") for letter in "AB"]
        db.add_all([model, *customers])
        db.flush()
        orders = [SalesOrder(order_no=f"SO-{letter}-{marker}", customer_id=customer.id,
                             order_type="client_order", status="ready_to_ship")
                  for letter, customer in zip("AB", customers)]
        db.add_all(orders)
        db.flush()
        db.add_all([SalesOrderItem(sales_order_id=order.id, model_id=model.id, color="navy", size="48",
                                  quantity=8, unit_price=10) for order in orders])
        production = ProductionOrder(production_no=f"PO-{marker}", production_type="client_order",
                                     sales_order_id=orders[0].id, model_id=model.id, planned_quantity=16)
        db.add(production)
        db.flush()
        packs = []
        for index in range(2):
            package = Package(package_no=f"PK-{index}-{marker}", barcode=f"QR-{index}-{marker}",
                              production_order_id=production.id, sales_order_id=None,
                              model_id=model.id, color="navy", capacity=60, total_quantity=8,
                              status="received_in_storage")
            db.add(package)
            db.flush()
            db.add(PackageItem(package_id=package.id, model_id=model.id, color="navy", size="48", quantity=8))
            db.add(FinishedGoodsStock(package_id=package.id, production_order_id=production.id,
                                      sales_order_id=orders[0].id, model_id=model.id, color="navy", size="48",
                                      quantity=8, available_qty=8, reserved_qty=0, sold_qty=0, status="available"))
            packs.append(package)
        shipments = [Shipment(shipment_no=f"SH-{letter}-{marker}", customer_id=customer.id, status="created")
                     for letter, customer in zip("AB", customers)]
        db.add_all(shipments)
        db.commit()
        return {"packs": [package.id for package in packs], "codes": [package.barcode for package in packs],
                "orders": [order.id for order in orders], "customers": [customer.id for customer in customers],
                "shipments": [shipment.id for shipment in shipments], "production": production.id}


@pytest.fixture
def warehouse_headers(client):
    response = client.post("/api/auth/token", data={"username": "fgs@example.com", "password": "demo12345"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def business_snapshot():
    """Exclude rejection scan/audit history, but include all inventory and claims."""
    with SessionLocal() as db:
        return {model.__tablename__: db.execute(select(model.__table__).order_by(model.id)).all()
                for model in (Package, PackageItem, FinishedGoodsStock, StockMovement, StockReservation,
                              WarehousePackReservation, ShipmentPackage, SalesOrder, ProductionOrder, Shipment)}


def scan(client, headers, data, customer=1, package=0):
    return client.post(f"/api/shipments/{data['shipments'][customer]}/scan-package", headers=headers,
                       json={"code": data["codes"][package]})


def release(client, headers, data, **overrides):
    return client.post("/api/packages/customer-release", headers=headers,
                       json={"package_ids": data["packs"], "reason": "  Owner released remaining stock  ", **overrides})


def test_production_source_blocks_cross_customer_scan_after_package_order_link_cleared(client, auth_headers, customer_packs):
    before = business_snapshot()
    response = scan(client, auth_headers, customer_packs)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is False, response.text
    assert "Customer A" in response.json()["message"]
    assert business_snapshot() == before


def test_same_customer_can_scan_source_pack_into_manual_shipment(client, auth_headers, customer_packs):
    response = scan(client, auth_headers, customer_packs, customer=0)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True, response.text


@pytest.mark.parametrize("endpoint", ["ship", "mark-shipped"])
def test_both_dispatch_endpoints_recheck_customer_after_successful_scan(client, auth_headers, customer_packs, endpoint):
    assert scan(client, auth_headers, customer_packs, customer=0).json()["ok"] is True
    sid = customer_packs["shipments"][0]
    with SessionLocal() as db:
        db.get(Shipment, sid).customer_id = customer_packs["customers"][1]
        db.commit()
    before = business_snapshot()
    response = client.post(f"/api/shipments/{sid}/{endpoint}", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert "Customer A" in response.text
    assert business_snapshot() == before


def test_direct_attachment_and_standalone_ship_cannot_bypass_source_customer(client, auth_headers, customer_packs):
    pid = customer_packs["packs"][0]
    sid = customer_packs["shipments"][1]
    before = business_snapshot()
    for url in [f"/api/shipments/{sid}/add-package?package_id={pid}", f"/api/packages/{pid}/ship"]:
        response = client.post(url, headers=auth_headers)
        assert response.status_code == 409, response.text
        assert business_snapshot() == before


def test_order_customer_header_override_rejected_even_after_pack_release(client, auth_headers, customer_packs):
    assert release(client, auth_headers, customer_packs).status_code == 200
    before = business_snapshot()
    response = client.post("/api/shipments", headers=auth_headers,
                           json={"sales_order_id": customer_packs["orders"][0],
                                 "customer_id": customer_packs["customers"][1]})
    assert response.status_code == 409, response.text
    assert business_snapshot() == before


def test_admin_release_preserves_inventory_origin_and_is_idempotent(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    before = business_snapshot()
    with SessionLocal() as db:
        audits_before = db.query(AuditLog).count()
        admin_id = db.query(User.id).filter_by(email="admin@example.com").scalar()
    first = release(client, auth_headers, customer_packs)
    assert first.status_code == 200, first.text
    assert first.json() == {"package_ids": customer_packs["packs"], "released_count": 2}
    assert business_snapshot() == before
    with SessionLocal() as db:
        rows = db.query(PackageCustomerRelease).order_by(PackageCustomerRelease.package_id).all()
        assert [row.package_id for row in rows] == customer_packs["packs"]
        assert all(row.released_by == admin_id and row.released_at is not None for row in rows)
        assert all(row.reason == "Owner released remaining stock" and row.released_quantity == 8 for row in rows)
        assert all(row.source_order_ids == [customer_packs["orders"][0]] for row in rows)
        audits_after = db.query(AuditLog).count()
        assert audits_after > audits_before
        release_rows = db.execute(select(PackageCustomerRelease.__table__).order_by(PackageCustomerRelease.package_id)).all()
    retried = release(client, auth_headers, customer_packs, reason="Repeated click")
    assert retried.status_code == 200 and retried.json() == first.json(), retried.text
    with SessionLocal() as db:
        assert db.query(AuditLog).count() == audits_after
        assert db.execute(select(PackageCustomerRelease.__table__).order_by(PackageCustomerRelease.package_id)).all() == release_rows
    assert business_snapshot() == before
    scanned = scan(client, auth_headers, customer_packs)
    assert scanned.status_code == 200 and scanned.json()["ok"] is True, scanned.text


def test_warehouse_user_cannot_release_customer_restriction(client, warehouse_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    before = business_snapshot()
    response = release(client, warehouse_headers, customer_packs)
    assert response.status_code == 403, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 0


@pytest.mark.parametrize("overrides", [
    {"package_ids": []}, {"package_ids": [0]}, {"package_ids": [-1]}, {"package_ids": [True]},
    {"package_ids": [1.5]}, {"package_ids": ["1"]}, {"package_ids": [1, 1]},
    {"package_ids": list(range(1, 202))}, {"reason": "  "}, {"reason": "a" * 1001},
])
def test_release_contract_rejects_invalid_request_without_mutations(client, auth_headers, customer_packs, overrides):
    from app.schemas import PackageCustomerRelease

    before = business_snapshot()
    response = release(client, auth_headers, customer_packs, **overrides)
    assert response.status_code == 422, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 0


@pytest.mark.parametrize("obstacle", ["not_received", "warehouse_reserved", "stock_reserved", "stock_only_reserved",
                                       "shipment_claim", "missing_stock", "unbalanced_stock", "no_remaining"])
def test_release_batch_is_atomic_and_preserves_reservations(client, auth_headers, customer_packs, obstacle):
    from app.schemas import PackageCustomerRelease

    pid = customer_packs["packs"][1]
    with SessionLocal() as db:
        package = db.get(Package, pid)
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        if obstacle == "not_received":
            package.status = "packed"
        elif obstacle == "warehouse_reserved":
            admin_id = db.query(User.id).filter_by(email="admin@example.com").scalar()
            db.add(WarehousePackReservation(package_id=pid, customer_id=customer_packs["customers"][0],
                                             quantity=8, reserved_by=admin_id))
        elif obstacle in {"stock_reserved", "stock_only_reserved"}:
            db.add(StockReservation(sales_order_id=customer_packs["orders"][0], finished_goods_stock_id=stock.id,
                                    package_id=pid if obstacle == "stock_reserved" else None, quantity=1))
        elif obstacle == "shipment_claim":
            db.add(ShipmentPackage(shipment_id=customer_packs["shipments"][0], package_id=pid, quantity=1))
        elif obstacle == "missing_stock":
            db.delete(stock)
        elif obstacle == "unbalanced_stock":
            stock.available_qty = 7
        elif obstacle == "no_remaining":
            package.dispatched_quantity = 8
            stock.sold_qty = 8
            stock.available_qty = 0
        db.commit()
        audits = db.query(AuditLog).count()
    before = business_snapshot()
    response = release(client, auth_headers, customer_packs)
    assert response.status_code == 409, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 0
        assert db.query(AuditLog).count() == audits


def test_missing_pack_rolls_back_entire_release_batch(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    before = business_snapshot()
    response = release(client, auth_headers, customer_packs, package_ids=[*customer_packs["packs"], 2147483647])
    assert response.status_code == 404, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 0


def test_release_applies_only_to_remaining_partial_pack(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    pid = customer_packs["packs"][0]
    with SessionLocal() as db:
        package = db.get(Package, pid)
        item = db.query(PackageItem).filter_by(package_id=pid).one()
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        package.dispatched_quantity = 3
        package.dispatched_quantities = {str(item.id): 3}
        stock.available_qty, stock.sold_qty = 5, 3
        db.commit()
    assert scan(client, auth_headers, customer_packs).json()["ok"] is False
    before = business_snapshot()
    response = release(client, auth_headers, customer_packs, package_ids=[pid])
    assert response.status_code == 200, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.get(PackageCustomerRelease, pid).released_quantity == 5
    assert scan(client, auth_headers, customer_packs).json()["ok"] is True


def test_release_does_not_override_later_warehouse_reservation(client, auth_headers, customer_packs):
    assert release(client, auth_headers, customer_packs).status_code == 200
    with SessionLocal() as db:
        admin_id = db.query(User.id).filter_by(email="admin@example.com").scalar()
        db.add(WarehousePackReservation(package_id=customer_packs["packs"][0],
                                        customer_id=customer_packs["customers"][0], quantity=8, reserved_by=admin_id))
        db.commit()
    before = business_snapshot()
    scanned = scan(client, auth_headers, customer_packs)
    assert scanned.status_code == 200 and scanned.json()["ok"] is False, scanned.text
    assert business_snapshot() == before


def test_release_stale_after_production_origin_changes(client, auth_headers, customer_packs):
    assert release(client, auth_headers, customer_packs).status_code == 200
    with SessionLocal() as db:
        db.get(ProductionOrder, customer_packs["production"]).sales_order_id = customer_packs["orders"][1]
        db.commit()
    scanned = scan(client, auth_headers, customer_packs, customer=0)
    assert scanned.status_code == 200 and scanned.json()["ok"] is False, scanned.text


def test_release_with_order_link_preserved_can_scan_into_another_sales_order(client, auth_headers, customer_packs):
    pid = customer_packs["packs"][0]
    sid = customer_packs["shipments"][1]
    with SessionLocal() as db:
        db.get(Package, pid).sales_order_id = customer_packs["orders"][0]
        db.get(Shipment, sid).sales_order_id = customer_packs["orders"][1]
        db.query(SalesOrderItem).filter_by(sales_order_id=customer_packs["orders"][1]).one().requested_pack_count = 1
        db.commit()
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    response = scan(client, auth_headers, customer_packs)
    assert response.status_code == 200 and response.json()["ok"] is True, response.text
    with SessionLocal() as db:
        assert db.get(Package, pid).sales_order_id == customer_packs["orders"][0]
        assert db.get(ProductionOrder, customer_packs["production"]).sales_order_id == customer_packs["orders"][0]
    dispatched = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert dispatched.status_code == 200, dispatched.text
    with SessionLocal() as db:
        assert db.get(Shipment, sid).status == "shipped"
        assert db.get(Package, pid).status == "shipped"
        assert db.get(Package, pid).sales_order_id == customer_packs["orders"][0]
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=pid).all()
        assert sum(row.sold_qty for row in stocks) == 8
        assert sum(row.available_qty + row.reserved_qty for row in stocks) == 0


def test_reopened_larger_remainder_needs_fresh_admin_release(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    pid = customer_packs["packs"][0]
    with SessionLocal() as db:
        package = db.get(Package, pid)
        item = db.query(PackageItem).filter_by(package_id=pid).one()
        package.dispatched_quantity, package.dispatched_quantities = 3, {str(item.id): 3}
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        stock.available_qty, stock.sold_qty = 5, 3
        db.commit()
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    with SessionLocal() as db:
        package = db.get(Package, pid)
        package.dispatched_quantity, package.dispatched_quantities = 0, {}
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        stock.available_qty, stock.sold_qty = 8, 0
        db.commit()
    assert scan(client, auth_headers, customer_packs).json()["ok"] is False
    assert release(client, auth_headers, customer_packs, package_ids=[pid], reason="Release reopened remainder").status_code == 200
    with SessionLocal() as db:
        assert db.get(PackageCustomerRelease, pid).released_quantity == 8
    assert scan(client, auth_headers, customer_packs).json()["ok"] is True


def test_conflicting_package_and_production_customers_fail_closed(client, auth_headers, customer_packs):
    with SessionLocal() as db:
        db.get(Package, customer_packs["packs"][0]).sales_order_id = customer_packs["orders"][1]
        db.commit()
    before = business_snapshot()
    for customer in [0, 1]:
        response = scan(client, auth_headers, customer_packs, customer=customer)
        assert response.status_code == 200 and response.json()["ok"] is False, response.text
        assert business_snapshot() == before


def test_admin_release_then_manual_scan_and_dispatch_consumes_existing_stock(client, auth_headers, customer_packs):
    pid = customer_packs["packs"][0]
    sid = customer_packs["shipments"][1]
    with SessionLocal() as db:
        db.get(Package, pid).sales_order_id = customer_packs["orders"][0]
        db.get(Shipment, sid).dispatch_snapshot = {"manual": True}
        stock_count = db.query(FinishedGoodsStock).count()
        db.commit()
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    response = scan(client, auth_headers, customer_packs)
    assert response.status_code == 200 and response.json()["ok"] is True, response.text
    dispatched = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert dispatched.status_code == 200, dispatched.text
    with SessionLocal() as db:
        assert db.get(Shipment, sid).status == "shipped"
        package = db.get(Package, pid)
        assert package.status == "shipped" and package.sales_order_id == customer_packs["orders"][0]
        assert package.production_order_id == customer_packs["production"]
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (8, 0, 0, 8)
        assert db.query(FinishedGoodsStock).count() == stock_count


def test_admin_release_enforces_factory_access_before_any_batch_write(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    with SessionLocal() as db:
        admin = db.query(User).filter_by(email="admin@example.com").one()
        admin.department_id = db.query(Department.id).filter_by(code="PKG").scalar()
        db.get(Package, customer_packs["packs"][1]).packaging_department_code = "BPK"
        db.commit()
    before = business_snapshot()
    response = release(client, auth_headers, customer_packs)
    assert response.status_code == 403, response.text
    assert business_snapshot() == before
    denied_read = client.get(f"/api/packages/{customer_packs['packs'][1]}/customer-access", headers=auth_headers)
    assert denied_read.status_code == 403, denied_read.text
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 0


def test_customer_access_readback_shows_actual_release_and_reason(client, auth_headers, customer_packs):
    pid = customer_packs["packs"][0]
    url = f"/api/packages/{pid}/customer-access"
    before = client.get(url, headers=auth_headers)
    assert before.status_code == 200, before.text
    assert before.json()["released_for_any_customer"] is False
    assert len(before.json()["customer_names"]) == 1
    assert "Customer A" in before.json()["customer_names"][0]
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    after = client.get(url, headers=auth_headers)
    assert after.status_code == 200, after.text
    assert after.json()["released_for_any_customer"] is True
    assert after.json()["release_reason"] == "Owner released remaining stock"
    assert after.json()["released_quantity"] == 8
    assert after.json()["released_at"] and after.json()["released_by_name"]


def test_actual_partial_dispatch_preserves_direct_only_customer_restriction(client, auth_headers, customer_packs):
    pid, sid = customer_packs["packs"][0], customer_packs["shipments"][0]
    with SessionLocal() as db:
        db.get(ProductionOrder, customer_packs["production"]).sales_order_id = None
        db.get(Package, pid).sales_order_id = customer_packs["orders"][0]
        db.get(Shipment, sid).sales_order_id = customer_packs["orders"][0]
        item_id = db.query(PackageItem.id).filter_by(package_id=pid).scalar()
        db.commit()
    assert scan(client, auth_headers, customer_packs, customer=0).json()["ok"] is True
    selected = client.post(f"/api/shipments/{sid}/packages/{pid}/quantity", headers=auth_headers,
                           json={"expected_quantity": 8, "keep_remainder": True, "reason": "Ship three pieces now",
                                 "items": [{"item_id": item_id, "quantity": 3}]})
    assert selected.status_code == 200, selected.text
    dispatched = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert dispatched.status_code == 200, dispatched.text
    with SessionLocal() as db:
        package = db.get(Package, pid)
        assert package.sales_order_id is None and package.dispatched_quantity == 3
        assert package.status == "received_in_storage" and package.total_quantity == 8
        assert db.get(ProductionOrder, customer_packs["production"]).sales_order_id is None
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert stock.sales_order_id == customer_packs["orders"][0]
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (8, 5, 0, 3)
    before = business_snapshot()
    denied = scan(client, auth_headers, customer_packs)
    assert denied.status_code == 200 and denied.json()["ok"] is False, denied.text
    assert "Customer A" in denied.json()["message"]
    assert business_snapshot() == before
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    assert scan(client, auth_headers, customer_packs).json()["ok"] is True


def test_released_source_packs_are_available_for_new_ready_stock_customer(client, auth_headers, customer_packs):
    with SessionLocal() as db:
        model_id = db.get(Package, customer_packs["packs"][0]).model_id
        for package in db.query(Package).filter(Package.id.in_(customer_packs["packs"])):
            package.sales_order_id = customer_packs["orders"][0]
        db.commit()
        source_stock = [(row.id, row.sales_order_id, row.production_order_id)
                        for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(customer_packs["packs"])).order_by(FinishedGoodsStock.id)]
    url = "/api/sales-orders/ready-stock-options"
    before = client.get(url, headers=auth_headers)
    assert before.status_code == 200, before.text
    assert not [row for row in before.json() if row["model_id"] == model_id]
    assert release(client, auth_headers, customer_packs).status_code == 200
    options = client.get(url, headers=auth_headers)
    assert options.status_code == 200, options.text
    assert next(row for row in options.json() if row["model_id"] == model_id) == {
        "model_id": model_id, "brand_id": None, "pack_count": 2, "quantity": 16}
    created = client.post("/api/sales-orders", headers=auth_headers,
                          json={"customer_id": customer_packs["customers"][1], "order_type": "branded_stock_sale",
                                "items": [{"model_id": model_id, "color": "mixed", "size": "any",
                                           "requested_pack_count": 2, "unit_price": 10}]})
    assert created.status_code == 201, created.text
    oid = created.json()["id"]
    assert created.json()["items"][0]["quantity"] == 16
    with SessionLocal() as db:
        reservations = db.query(StockReservation).filter_by(sales_order_id=oid).all()
        assert {row.package_id for row in reservations} == set(customer_packs["packs"])
        assert sum(row.quantity for row in reservations) == 16
        assert [(row.id, row.sales_order_id, row.production_order_id)
                for row in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(customer_packs["packs"])).order_by(FinishedGoodsStock.id)] == source_stock
        assert all(row.sales_order_id == customer_packs["orders"][0]
                   for row in db.query(Package).filter(Package.id.in_(customer_packs["packs"])))
    shipment = client.post("/api/shipments", headers=auth_headers, json={"sales_order_id": oid})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    for code in customer_packs["codes"]:
        scanned = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": code})
        assert scanned.status_code == 200 and scanned.json()["ok"] is True, scanned.text
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        stocks = db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(customer_packs["packs"])).all()
        assert sum(row.sold_qty for row in stocks) == 16
        assert sum(row.available_qty + row.reserved_qty for row in stocks) == 0
        assert all(row.sales_order_id == customer_packs["orders"][0] for row in stocks)


def test_released_source_pack_can_follow_warehouse_reserve_prepare_scan_dispatch(client, auth_headers, customer_packs):
    pid = customer_packs["packs"][0]
    with SessionLocal() as db:
        db.get(Package, pid).sales_order_id = customer_packs["orders"][0]
        db.commit()
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    reserved = client.post("/api/warehouse-reservations", headers=auth_headers,
                           json={"customer_id": customer_packs["customers"][1], "package_ids": [pid]})
    assert reserved.status_code == 200, reserved.text
    prepared = client.post("/api/warehouse-reservations/prepare-shipment", headers=auth_headers,
                           json={"package_ids": [pid]})
    assert prepared.status_code == 200, prepared.text
    sid = prepared.json()["id"]
    scanned = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers,
                          json={"code": customer_packs["codes"][0]})
    assert scanned.status_code == 200 and scanned.json()["ok"] is True, scanned.text
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        assert db.get(Package, pid).sales_order_id == customer_packs["orders"][0]
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert stock.sales_order_id == customer_packs["orders"][0]
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (8, 0, 0, 8)


def test_bulk_200_source_packs_and_ten_retries_preserve_stock_and_single_audits(client, auth_headers, customer_packs):
    from app.schemas import PackageCustomerRelease

    with SessionLocal() as db:
        template = db.get(Package, customer_packs["packs"][0])
        model_id, po_id, oid = template.model_id, template.production_order_id, customer_packs["orders"][0]
        ids = list(customer_packs["packs"])
        marker = uuid4().hex
        for index in range(198):
            package = Package(package_no=f"BULK-{index}-{marker}", barcode=f"BQ-{index}-{marker}",
                              production_order_id=po_id, sales_order_id=oid, model_id=model_id, color="navy",
                              total_quantity=8, capacity=60, status="received_in_storage")
            db.add(package)
            db.flush()
            ids.append(package.id)
            db.add(PackageItem(package_id=package.id, model_id=model_id, color="navy", size="48", quantity=8))
            db.add(FinishedGoodsStock(package_id=package.id, model_id=model_id, production_order_id=po_id,
                                      sales_order_id=oid, color="navy", size="48", quantity=8,
                                      available_qty=8, reserved_qty=0, sold_qty=0, status="available"))
        db.commit()
        before_audits = db.query(AuditLog).count()
    before = business_snapshot()
    too_many = release(client, auth_headers, customer_packs, package_ids=[*ids, 2147483647])
    assert too_many.status_code == 422, too_many.text
    first = release(client, auth_headers, customer_packs, package_ids=list(reversed(ids)))
    assert first.status_code == 200, first.text
    assert first.json() == {"package_ids": ids, "released_count": 200}
    for _ in range(10):
        response = release(client, auth_headers, customer_packs, package_ids=ids)
        assert response.status_code == 200 and response.json() == first.json(), response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(PackageCustomerRelease).count() == 200
        assert db.query(AuditLog).count() == before_audits + 200
        assert all(row.released_quantity == 8 and row.source_order_ids == [oid]
                   for row in db.query(PackageCustomerRelease))


@pytest.mark.parametrize("stock_only", [False, True])
@pytest.mark.parametrize("operation", ["scan", "add", "standalone_ship"])
def test_released_pack_cannot_be_attached_against_later_foreign_stock_reservation(
        client, auth_headers, customer_packs, stock_only, operation):
    pid, sid = customer_packs["packs"][0], customer_packs["shipments"][0]
    with SessionLocal() as db:
        db.get(Package, pid).sales_order_id = customer_packs["orders"][0]
        db.get(Shipment, sid).sales_order_id = customer_packs["orders"][0]
        db.commit()
    assert release(client, auth_headers, customer_packs, package_ids=[pid]).status_code == 200
    with SessionLocal() as db:
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        stock.available_qty, stock.reserved_qty, stock.status = 0, 8, "reserved"
        db.get(Package, pid).status = "reserved"
        db.add(StockReservation(sales_order_id=customer_packs["orders"][1], finished_goods_stock_id=stock.id,
                                package_id=None if stock_only else pid, quantity=8))
        db.commit()
    before = business_snapshot()
    if operation == "scan":
        response = scan(client, auth_headers, customer_packs, customer=0)
        assert response.status_code == 200 and response.json()["ok"] is False, response.text
    elif operation == "add":
        response = client.post(f"/api/shipments/{sid}/add-package?package_id={pid}", headers=auth_headers)
        assert response.status_code == 409, response.text
    else:
        response = client.post(f"/api/packages/{pid}/ship", headers=auth_headers)
        assert response.status_code == 409, response.text
    assert business_snapshot() == before
    with SessionLocal() as db:
        assert db.query(ShipmentPackage).filter_by(shipment_id=sid, package_id=pid).count() == 0
        assert db.query(ShipmentScanLog).filter_by(shipment_id=sid, package_id=pid, scan_result="matched").count() == 0
        reservation = db.query(StockReservation).filter_by(sales_order_id=customer_packs["orders"][1]).one()
        assert reservation.quantity == 8 and reservation.package_id == (None if stock_only else pid)
