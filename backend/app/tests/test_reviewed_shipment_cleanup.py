import importlib.util
from pathlib import Path
from decimal import Decimal
import pytest
from app.db.session import SessionLocal
from app.models import Shipment, Package, FinishedGoodsStock, Invoice, SalesOrder, StockReservation, AuditLog, Payment
from app.tests.test_shipment_review import dispatch  # noqa: F401

spec = importlib.util.spec_from_file_location("cleanup", Path(__file__).parents[2] / "scripts" / "reset_reviewed_shipments.py")
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


@pytest.fixture
def shipped(dispatch):
    with SessionLocal() as db:
        shipment = db.get(Shipment, dispatch["shipment"])
        shipment.status = "shipped"
        shipment.dispatch_snapshot = {"manual": True}
        order = db.get(SalesOrder, dispatch["order"])
        order.notes = "Manual shipment " + shipment.shipment_no
        order.status = "shipped"
        db.get(Package, dispatch["package"]).status = "shipped"
        db.query(StockReservation).filter_by(package_id=dispatch["package"]).delete()
        for row in db.query(FinishedGoodsStock).filter_by(package_id=dispatch["package"]):
            row.available_qty = row.reserved_qty = 0
            row.sold_qty = row.quantity
            row.status = "sold"
        db.add(Invoice(sales_order_id=order.id, invoice_no="CLEANUP-INV", amount=80, status="unpaid"))
        db.commit()
    return dispatch


def test_preview_and_fingerprint_prevent_changed_selection(shipped):
    with SessionLocal() as db:
        _, fingerprint, _ = cleanup.prepare(db, [shipped["shipment"]])
        assert len(fingerprint) == 64
        assert db.get(Package, shipped["package"]).status == "shipped"
        with pytest.raises(ValueError, match="fingerprint"):
            cleanup.apply_reviewed(db, [shipped["shipment"]], "wrong")
        db.rollback()
        assert db.query(FinishedGoodsStock).filter_by(package_id=shipped["package"]).first().sold_qty == 4


def test_return_and_delete_preserve_stock_and_accounting_evidence(shipped):
    with SessionLocal() as db:
        stock_ids = [r.id for r in db.query(FinishedGoodsStock).filter_by(package_id=shipped["package"])]
        _, fingerprint, _ = cleanup.prepare(db, [shipped["shipment"]])
        summary = cleanup.apply_reviewed(db, [shipped["shipment"]], fingerprint)
        db.commit()
    with SessionLocal() as db:
        assert summary["pieces_restored"] == 8
        assert db.get(Shipment, shipped["shipment"]) is None
        assert db.get(Package, shipped["package"]).status == "received_in_storage"
        stocks = db.query(FinishedGoodsStock).filter_by(package_id=shipped["package"]).all()
        assert [r.id for r in stocks] == stock_ids
        assert sum(r.available_qty for r in stocks) == 8
        assert sum(r.sold_qty for r in stocks) == 0
        invoice = db.query(Invoice).filter_by(invoice_no="CLEANUP-INV").one()
        assert invoice.status == "void" and invoice.amount == Decimal("0")
        assert db.get(SalesOrder, shipped["order"]).status == "cancelled"
        evidence = db.query(AuditLog).filter_by(action="reviewed_shipment_cleanup_20260919").one()
        assert evidence.old_value_json["invoices"][0]["amount"] in (80, 80.0, "80.00")
        with pytest.raises(ValueError, match="selection"):
            cleanup.prepare(db, [shipped["shipment"]])


def test_payment_blocks_entire_cleanup(shipped):
    with SessionLocal() as db:
        invoice = db.query(Invoice).filter_by(invoice_no="CLEANUP-INV").one()
        db.add(Payment(invoice_id=invoice.id, amount=1))
        db.commit()
        with pytest.raises(ValueError, match="paid invoice"):
            cleanup.prepare(db, [shipped["shipment"]])
        assert db.get(Package, shipped["package"]).status == "shipped"
