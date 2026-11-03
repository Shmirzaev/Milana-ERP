"""Real lock contention and rollback on the identity-pinned disposable PG target."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.api.routes.warehouse_reservations import ReservePacks, reserve_packs
from app.libs.dto.fulfillment.package_customer_release import PackageCustomerReleaseIn
from app.models.fulfillment.package_customer_service import release_packages_for_any_customer
from app.schemas import (
    AuditLog, Customer, FinishedGoodsStock, Model, Package, PackageCustomerRelease,
    PackageItem, ProductionOrder, Role, SalesOrder, User, WarehousePackReservation,
)
from app.tests.test_customer_create_postgres import customer_pg_sessions, chain  # noqa: F401


def release_fixture(sessions):
    marker = uuid4().hex
    with sessions.begin() as db:
        model = Model(code=marker, name="Customer release PG", status="approved")
        customer = Customer(name="Customer release " + marker)
        role = Role(name="Customer release " + marker, permissions=["*"])
        db.add_all([model, customer, role])
        db.flush()
        actor = User(name="Release QA", email=marker + "@qa.invalid", password_hash="unused", role_id=role.id)
        order = SalesOrder(order_no="SO-" + marker, customer_id=customer.id, order_type="client_order", status="ready_to_ship")
        db.add_all([actor, order])
        db.flush()
        production = ProductionOrder(production_no="PO-" + marker, production_type="client_order",
                                     sales_order_id=order.id, model_id=model.id, planned_quantity=8)
        db.add(production)
        db.flush()
        package = Package(package_no="PK-" + marker, barcode="QR-" + marker, production_order_id=production.id,
                          sales_order_id=order.id, model_id=model.id, color="navy", total_quantity=8,
                          capacity=60, status="received_in_storage")
        db.add(package)
        db.flush()
        db.add(PackageItem(package_id=package.id, model_id=model.id, color="navy", size="48", quantity=8))
        db.add(FinishedGoodsStock(package_id=package.id, model_id=model.id, color="navy", size="48",
                                  quantity=8, available_qty=8, reserved_qty=0, sold_qty=0, status="available"))
        return package.id, actor.id, customer.id


def test_pg_competing_releases_create_one_release_and_one_audit(customer_pg_sessions):
    sessions = customer_pg_sessions
    pid, uid, _ = release_fixture(sessions)
    barrier = Barrier(2)

    def worker(index):
        with sessions() as db:
            actor = db.get(User, uid)
            barrier.wait(timeout=10)
            result = release_packages_for_any_customer(
                PackageCustomerReleaseIn(package_ids=[pid], reason=f"Concurrent release {index}"), db, actor)
            return result.model_dump()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert results == [{"package_ids": [pid], "released_count": 1}] * 2
    with sessions() as db:
        assert db.query(PackageCustomerRelease).filter_by(package_id=pid).count() == 1
        assert db.query(AuditLog).filter_by(entity_type="Package", entity_id=pid, action="release_for_any_customer").count() == 1
        package = db.get(Package, pid)
        assert package.status == "received_in_storage" and package.total_quantity == 8
        assert package.sales_order_id is not None and package.production_order_id is not None
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (8, 8, 0, 0)
    chain(sessions)


def test_pg_release_and_customer_reservation_serialize_without_lost_stock(customer_pg_sessions):
    sessions = customer_pg_sessions
    pid, uid, cid = release_fixture(sessions)
    # Reservation API rejects source-owned packs. Clear only the mutable package
    # association, retaining the production order's authoritative customer.
    with sessions.begin() as db:
        db.get(Package, pid).sales_order_id = None
    barrier = Barrier(2)

    def worker(action):
        with sessions() as db:
            actor = db.get(User, uid)
            barrier.wait(timeout=10)
            try:
                if action == "release":
                    release_packages_for_any_customer(PackageCustomerReleaseIn(package_ids=[pid], reason="Stock release"), db, actor)
                else:
                    reserve_packs(ReservePacks(customer_id=cid, package_ids=[pid]), db, actor, None)
                return action, 200
            except HTTPException as rejected:
                db.rollback()
                return action, rejected.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(worker, ("release", "reserve")))
    assert results["reserve"] == 200, results
    assert results["release"] in (200, 409), results
    with sessions() as db:
        hold = db.query(WarehousePackReservation).filter_by(package_id=pid).one()
        assert hold.customer_id == cid and hold.quantity == 8
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert (stock.quantity, stock.available_qty, stock.reserved_qty, stock.sold_qty) == (8, 0, 8, 0)
        assert db.query(PackageCustomerRelease).filter_by(package_id=pid).count() == (1 if results["release"] == 200 else 0)
    chain(sessions)


def test_pg_precommit_failure_rolls_back_release_and_audit_then_retry(customer_pg_sessions):
    sessions = customer_pg_sessions
    pid, uid, _ = release_fixture(sessions)

    def fail(_session):
        raise RuntimeError("injected customer-release precommit failure")

    payload = PackageCustomerReleaseIn(package_ids=[pid], reason="Retry after failed transaction")
    with sessions() as db:
        event.listen(db, "before_commit", fail)
        with pytest.raises(RuntimeError, match="injected customer-release"):
            release_packages_for_any_customer(payload, db, db.get(User, uid))
        event.remove(db, "before_commit", fail)
        db.rollback()
    with sessions() as db:
        assert db.get(PackageCustomerRelease, pid) is None
        assert db.query(AuditLog).filter_by(entity_type="Package", entity_id=pid, action="release_for_any_customer").count() == 0
        stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
        assert stock.available_qty == 8 and stock.reserved_qty == stock.sold_qty == 0
        result = release_packages_for_any_customer(payload, db, db.get(User, uid))
        assert result.released_count == 1
    with sessions() as db:
        assert db.query(AuditLog).filter_by(entity_type="Package", entity_id=pid, action="release_for_any_customer").count() == 1
    chain(sessions)
