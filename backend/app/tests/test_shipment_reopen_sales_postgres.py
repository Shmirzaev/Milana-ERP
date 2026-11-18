"""Guarded PostgreSQL test for the Sales participant of shipment reopen.

The coordinator must supply an approved disposable instance. This exercises the
real coordinator and audit, but is not full shipment acceptance or lock stress.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.libs.dto.fulfillment.shipment_review import ShipmentReopen
from app.models.shipment_reopen_service import reopen_shipment
from app.schemas import (
    AuditLog, FinishedGoodsStock, LegacyStockReceipt, Model, Package, PackageItem,
    SalesOrder, Shipment, ShipmentPackage, StockReservation, User,
)
from app.tests.test_customer_create_postgres import customer_pg_sessions  # noqa: F401


def seed(sessions, manual):
    token = uuid4().hex
    now = datetime.now(timezone.utc)
    with sessions.begin() as db:
        user = User(name="Reopen PG", email=f"{token}@example.invalid", password_hash="unused")
        model = Model(code=f"RPG-{token}", name="Reopen PG")
        receipt = LegacyStockReceipt(source_system="TEST", source_warehouse_id="reopen",
                                     source_record_id=token, source_checksum="a" * 64,
                                     source_payload={"quantity": 8})
        db.add_all([user, model, receipt]); db.flush()
        shipment_no = f"RPG-SH-{token}"
        order = SalesOrder(order_no=f"RPG-SO-{token}", status="shipped", total_amount=Decimal("80.00"),
                           notes=f"Manual shipment {shipment_no}" if manual else "standard order")
        package = Package(package_no=f"RPG-P-{token}", barcode=f"RPG-B-{token}", model_id=model.id,
                          color="navy", capacity=60, total_quantity=8, legacy_receipt_id=receipt.id,
                          status="shipped", shipped_at=now)
        db.add_all([order, package]); db.flush()
        shipment = Shipment(shipment_no=shipment_no, sales_order_id=order.id, status="shipped",
                            shipped_at=now, dispatch_snapshot={"manual": True} if manual else None)
        stock = FinishedGoodsStock(package_id=package.id, model_id=model.id, color="navy", size="M",
                                   quantity=8, available_qty=0, reserved_qty=0, sold_qty=8, status="sold")
        db.add_all([shipment, stock, PackageItem(package_id=package.id, model_id=model.id,
                                                 color="navy", size="M", quantity=8)])
        db.flush()
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=package.id, quantity=8))
        if not manual:
            db.add(StockReservation(sales_order_id=order.id, package_id=package.id,
                                    finished_goods_stock_id=stock.id, quantity=8))
        db.flush()
        return user.id, order.id, shipment.id, package.id, stock.id, now


@pytest.mark.parametrize("manual", [True, False])
def test_pg_reopen_sales_participant_rollback_and_commit(customer_pg_sessions, manual):
    sessions = customer_pg_sessions
    uid, oid, sid, pid, stock_id, shipped_at = seed(sessions, manual)
    body = ShipmentReopen(reason="Returned for correction", packages_returned=True,
                          expected_shipped_at=shipped_at)
    with sessions() as db:
        result = reopen_shipment(db, sid, body, db.get(User, uid))
        order = db.get(SalesOrder, oid)
        assert (order.status, order.total_amount) == (
            ("cancelled", 0) if manual else ("ready_to_ship", Decimal("80.00")))
        assert result.sales_order_id == (None if manual else oid)
        assert db.in_transaction()
        db.rollback()
    with sessions() as db:
        order, shipment = db.get(SalesOrder, oid), db.get(Shipment, sid)
        assert (order.status, order.total_amount) == ("shipped", Decimal("80.00"))
        assert (shipment.status, shipment.sales_order_id) == ("shipped", oid)
        assert db.get(Package, pid).status == "shipped"
        assert db.get(FinishedGoodsStock, stock_id).sold_qty == 8
        assert db.query(AuditLog).filter_by(action="reopen_shipment", entity_id=sid).count() == 0
    with sessions.begin() as db:
        reopen_shipment(db, sid, body, db.get(User, uid))
    with sessions() as db:
        order, shipment = db.get(SalesOrder, oid), db.get(Shipment, sid)
        assert (order.status, order.total_amount) == (
            ("cancelled", Decimal("0.00")) if manual else ("ready_to_ship", Decimal("80.00")))
        assert (shipment.status, shipment.sales_order_id) == ("created", None if manual else oid)
        audit = db.query(AuditLog).filter_by(action="reopen_shipment", entity_id=sid).one()
        assert audit.old_value_json["order"]["status"] == "shipped"
        assert audit.new_value_json["status"] == "created"
