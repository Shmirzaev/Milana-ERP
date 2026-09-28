from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.api.routes.packages import _package_for_receiving_scan
from app.db.session import SessionLocal
from app.models import (
    AuditLog, FinishedGoodsStock, LegacyStockReceipt, Model, Package,
    PackageBarcodeAlias, PackageItem, Shipment, ShipmentPackage, User, Warehouse,
)
from app.models.stocktake import WarehouseStocktake, WarehouseStocktakeRow
from app.services.legacy_package_identity import apply_plan, build_plan, record
from app.services.package_identity import resolve_warehouse_package

CODES = [f"uzerp_ii_20818_{n}" for n in (1, 6, 10)]


@pytest.fixture
def consolidated():
    with SessionLocal() as db:
        model = db.query(Model).first()
        warehouse = db.query(Warehouse).first()
        actor = db.query(User).filter_by(email="admin@example.com").one()
        receipts = []
        for code in CODES:
            receipt = LegacyStockReceipt(
                source_system="UZERP_STICKER_PHOTO", source_warehouse_id="18", source_record_id=code,
                source_checksum="a" * 64, imported_by=actor.id,
                source_payload={"qr_code": code, "quantity": 60, "model_number": "XJ3062", "article": "V-5646",
                                "review_status": "approved", "source_photo_sha256": "b" * 64, "weight_kg": "27"},
            )
            db.add(receipt)
            receipts.append(receipt)
        db.flush()
        parent = Package(package_no="OLD-20818-10", barcode=CODES[-1], legacy_receipt_id=receipts[-1].id,
                         model_id=model.id, color="Blue", total_quantity=60, capacity=60,
                         warehouse_id=warehouse.id, status="received_in_storage", package_type="legacy_stock")
        db.add(parent)
        db.flush()
        db.add(PackageItem(package_id=parent.id, model_id=model.id, color=parent.color, size="M", quantity=60))
        db.add(FinishedGoodsStock(package_id=parent.id, model_id=model.id, color=parent.color, size="M",
                                 quantity=60, available_qty=60, reserved_qty=0, sold_qty=0,
                                 cost_per_piece=2, selling_price=5, warehouse_id=warehouse.id))
        db.add_all([PackageBarcodeAlias(package_id=parent.id, code=code, code_type="legacy_package_qr") for code in CODES[:-1]])
        db.commit()
        return parent.id, actor.id


def test_receiving_alias_preserved_but_warehouse_never_substitutes_sibling(consolidated):
    parent_id, _ = consolidated
    with SessionLocal() as db:
        assert _package_for_receiving_scan(db, CODES[0]).id == parent_id
        assert resolve_warehouse_package(db, CODES[0]) == (None, False)
        assert resolve_warehouse_package(db, CODES[-1]) == (parent_id, False)
        assert resolve_warehouse_package(db, f"PACKAGE:OLD-20818-10|{CODES[0]}") == (None, True)


def test_restore_count_and_ship_individual_qrs_once(client, auth_headers, consolidated):
    parent_id, actor_id = consolidated
    with SessionLocal() as db:
        parent_before = record(db.get(Package, parent_id))
        receipts_before = [record(r) for r in db.query(LegacyStockReceipt).order_by(LegacyStockReceipt.id)]
        plan = build_plan(db)
        assert plan["summary"]["restore_packages"] == 2 and plan["summary"]["restore_pieces"] == 120
        apply_plan(db, plan["sha256"], db.get(User, actor_id))
        db.commit()
        assert record(db.get(Package, parent_id)) == parent_before
        assert [record(r) for r in db.query(LegacyStockReceipt).order_by(LegacyStockReceipt.id)] == receipts_before
        assert build_plan(db)["operations"] == []
        ids = [resolve_warehouse_package(db, code)[0] for code in CODES]
        assert len(set(ids)) == 3
        for pid in ids[:-1]:
            stock = db.query(FinishedGoodsStock).filter_by(package_id=pid).one()
            assert stock.quantity == stock.available_qty == 60
            assert stock.cost_per_piece == 2 and stock.selling_price == 5
            assert stock.size == "ASSORTED"
    count = client.post("/api/warehouse-stocktakes", headers=auth_headers,
                        json={"request_key": str(uuid4()), "title": "Separate physical labels"})
    assert count.status_code == 200, count.text
    path = f"/api/warehouse-stocktakes/{count.json()['id']}"
    for code in CODES:
        scan = client.post(path + "/scan", headers=auth_headers, json={"code": code})
        assert scan.status_code == 200 and not scan.json()["duplicate"], scan.text
        assert scan.json()["row"]["result"] == "found"
    repeat = client.post(path + "/scan", headers=auth_headers, json={"code": CODES[0]})
    assert repeat.json()["duplicate"]
    summary = client.get(path, headers=auth_headers).json()["summary"]
    assert summary["scanned_packages"] == 3 and summary["scanned_pieces"] == 180
    shipment = client.post("/api/shipments", headers=auth_headers, json={"notes": "Physical package QR handoff"})
    assert shipment.status_code == 201, shipment.text
    sid = shipment.json()["id"]
    for number, code in enumerate(CODES, 1):
        result = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": code})
        assert result.status_code == 200 and result.json()["ok"], result.text
        assert result.json()["scanned_count"] == number
    result = client.post(f"/api/shipments/{sid}/scan-package", headers=auth_headers, json={"code": CODES[0]})
    assert result.json()["scanned_count"] == 3 and result.json()["sign"] == "warning"
    shipped = client.post(f"/api/shipments/{sid}/ship", headers=auth_headers)
    assert shipped.status_code == 200, shipped.text
    with SessionLocal() as db:
        assert all(db.get(Package, pid).status == "shipped" for pid in ids)
        assert sum(s.sold_qty for s in db.query(FinishedGoodsStock).filter(FinishedGoodsStock.package_id.in_(ids))) == 180
        duplicate = db.query(AuditLog).filter_by(action="scan_duplicate").one()
        assert duplicate.new_value_json["code"] == CODES[0]


@pytest.mark.parametrize("risk", ["delivered", "reserved", "shipment", "missing_evidence", "wrong_model", "defaulted_quantity"])
def test_reconciliation_excludes_unverified_or_committed_stock(consolidated, risk):
    parent_id, _ = consolidated
    with SessionLocal() as db:
        if risk == "delivered":
            db.get(Package, parent_id).status = "delivered"
        elif risk == "reserved":
            stock = db.query(FinishedGoodsStock).filter_by(package_id=parent_id).one()
            stock.available_qty, stock.reserved_qty = 0, 60
        elif risk == "shipment":
            sh = Shipment(shipment_no="LINKED", status="draft")
            db.add(sh)
            db.flush()
            db.add(ShipmentPackage(shipment_id=sh.id, package_id=parent_id, quantity=60))
        else:
            for receipt in db.query(LegacyStockReceipt).filter(LegacyStockReceipt.source_record_id.in_(CODES[:-1])):
                key, value = {"missing_evidence": ("source_photo_sha256", ""), "wrong_model": ("model_number", "DIFFERENT"),
                              "defaulted_quantity": ("quantity_defaulted", True)}[risk]
                receipt.source_payload = {**receipt.source_payload, key: value}
        db.commit()
        plan = build_plan(db)
        assert plan["operations"] == [] and len(plan["excluded"]) == 2


def test_guard_rejects_changed_plan_and_transaction_rolls_back(consolidated):
    parent_id, actor_id = consolidated
    with SessionLocal() as db:
        plan = build_plan(db)
        db.get(Package, parent_id).total_quantity = 59
        db.flush()
        with pytest.raises(ValueError, match="evidence changed"):
            apply_plan(db, plan["sha256"], db.get(User, actor_id))
        db.rollback()
        assert db.query(Package).filter(Package.barcode.in_(CODES)).count() == 1
        apply_plan(db, plan["sha256"], db.get(User, actor_id))
        db.rollback()
        assert db.query(Package).filter(Package.barcode.in_(CODES)).count() == 1


def test_open_scan_identity_is_corrected_without_rewriting_completed_count(consolidated):
    parent_id, actor_id = consolidated
    with SessionLocal() as db:
        counts = []
        for completed in (False, True):
            count = WarehouseStocktake(title="Existing", request_key=str(uuid4()), created_by=actor_id,
                                       completed_at=datetime.now(timezone.utc) if completed else None)
            db.add(count)
            db.flush()
            db.add(WarehouseStocktakeRow(stocktake_id=count.id, identity=f"package:{parent_id}", package_id=parent_id,
                                         expected=True, category="expected", snapshot={"barcode": CODES[-1]},
                                         scan_code=CODES[0], scanned_at=datetime.now(timezone.utc), scanned_by=actor_id,
                                         scan_snapshot={"barcode": CODES[-1], "quantity": 60}))
            counts.append(count.id)
        db.commit()
        result = apply_plan(db, build_plan(db)["sha256"], db.get(User, actor_id))
        assert result["corrected_open_scans"] == 1
        db.commit()
        old = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=counts[0], package_id=parent_id).one()
        assert old.scanned_at is None and old.snapshot == {"barcode": CODES[-1]}
        moved = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=counts[0], scan_code=CODES[0]).one()
        assert moved.package_id != parent_id and moved.scan_snapshot["barcode"] == CODES[0]
        assert not moved.expected and moved.category == "unexpected"
        assert "items" not in moved.snapshot
        closed = db.query(WarehouseStocktakeRow).filter_by(stocktake_id=counts[1]).one()
        assert closed.package_id == parent_id and closed.scan_code == CODES[0]
