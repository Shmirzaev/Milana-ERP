from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.schemas import (Bundle, BundleScanLog, CuttingRecord, Department, Model, Package,
                        ProductionBatch, ProductionOrder, Shipment, ShipmentPackage, WasteRecord, WorkOrder)
from app.models.department_dashboards_service import cutting_board, printing_board, warehouse_board
from app.tests.conftest import TestSessionLocal

STAMP = datetime(2026, 1, 1, 20, tzinfo=timezone.utc)  # January 2 in Tashkent
DAY = date(2026, 1, 2)


def order(db, name="BOARD", department="CUT"):
    model = db.query(Model).first()
    po = ProductionOrder(production_no=name, production_type="branded_stock", model_id=model.id, status="cutting")
    db.add(po)
    db.flush()
    dept = db.query(Department).filter_by(code=department).one()
    wo = WorkOrder(production_order_id=po.id, department_id=dept.id, operation="cutting", status="in_progress")
    db.add(wo)
    db.flush()
    record = CuttingRecord(work_order_id=wo.id, passed_pieces=100, approval_status="approved")
    db.add(record)
    db.flush()
    return po, wo, record


def bundle(db, po, record, name, factory="MIL", status="created", quantity=10, created=STAMP, next_dept="MIL"):
    dept = db.query(Department).filter_by(code=next_dept).one()
    row = Bundle(production_order_id=po.id, model_id=po.model_id, cutting_record_id=record.id,
                 bundle_no=name, barcode=name, color="blue", size="M", quantity=quantity,
                 sewing_factory_code=factory, status=status, created_at=created, next_department_id=dept.id)
    db.add(row)
    db.flush()
    return row


def test_cutting_factory_totals_full_not_paginated_and_distinct_work(client, auth_headers):
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        for i in range(55):
            bundle(db, po, rec, f"BOARD-B-{i}", factory="BST" if i % 2 else "MIL")
        bundle(db, po, rec, "BOARD-UNKNOWN", factory=None)
        db.commit()
        result = cutting_board(db, "CUT", DAY, DAY)
        assert result["totals"] == {"bundles": 56, "pieces": 560, "orders": 1, "work_orders": 1}
        factories = {r["factory"]: r for r in result["factories"]}
        assert factories["BST"]["bundles"] == 27
        assert factories["MIL"]["bundles"] == 28
        assert factories["UNASSIGNED"]["bundles"] == 1
    response = client.get("/api/bundles/cutting-inventory?destination_factory=BST&page_size=1", headers=auth_headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["rows"]) == 1
    assert result["total"] == 27 and result["total_quantity"] == 270
    assert result["total_work_orders"] == 1


def test_cutting_receipts_are_deduplicated_and_current_balance_is_not_date_filtered():
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        bundle(db, po, rec, "BOARD-OLD", created=datetime(2025, 1, 1, tzinfo=timezone.utc))
        sent = bundle(db, po, rec, "BOARD-PRINTED", status="sent_to_sewing")
        for kind in ["received_printing", "received_printing", "received_sewing"]:
            db.add(BundleScanLog(bundle_id=sent.id, scan_type=kind, scanned_at=STAMP))
        bundle(db, po, rec, "BOARD-CANCELLED", status="cancelled")
        db.commit()
        result = cutting_board(db, "CUT", DAY, DAY)
        assert result["totals"]["bundles"] == 1
        mil = next(r for r in result["factories"] if r["factory"] == "MIL")
        assert mil["transferred_bundles"] == 1 and mil["transferred_pieces"] == 10
        assert mil["created_bundles"] == 1


def test_cutting_waste_units_origin_and_business_day_boundaries():
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        for unit, qty, stamp, kind in [("kg", 5, STAMP, "cutting_waste"), ("m", 7, STAMP, "cutting_waste"),
                                      ("kg", 99, datetime(2026, 1, 1, 18, tzinfo=timezone.utc), "cutting_waste"),
                                      ("pcs", 88, STAMP, "sewing_defect"), ("kg", 3, STAMP, "fabric")]:
            db.add(WasteRecord(source_department_id=wo.department_id, waste_type=kind, quantity=qty, unit=unit, created_at=stamp))
        eco, eco_wo, eco_rec = order(db, "BOARD-ECO", "ECT")
        bundle(db, eco, eco_rec, "BOARD-ECO-BUNDLE", factory="ECO")
        db.add(WasteRecord(source_department_id=eco_wo.department_id, waste_type="cutting_waste", quantity=100, unit="kg", created_at=STAMP))
        db.commit()
        result = cutting_board(db, "CUT", DAY, DAY)
        assert {r["unit"]: r["quantity"] for r in result["waste"]} == {"kg": 8, "m": 7}
        assert result["totals"]["bundles"] == 0
        assert cutting_board(db, "ECT", DAY, DAY)["totals"]["bundles"] == 1


def test_printing_only_ready_bundle_groups_with_artwork_and_complete_totals():
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        po.printing_attachments = [{"file_url": "/storage/sales-order-files/art.png", "content_type": "image/png"}]
        batch = ProductionBatch(production_order_id=po.id, batch_no="1", batch_index=1, name="Nastil 1")
        db.add(batch)
        db.flush()
        for i in range(3):
            bundle(db, po, rec, f"BOARD-PRINT-{i}", next_dept="PRT", status="sent_to_printing").production_batch_id = batch.id
        bundle(db, po, rec, "BOARD-RECEIVED", next_dept="PRT", status="received_printing")
        bundle(db, po, rec, "BOARD-SEWING", next_dept="MIL")
        db.commit()
        result = printing_board(db, limit=1)
        assert result["totals"]["bundles"] == 3 and result["totals"]["pieces"] == 30
        assert result["total"] == 1
        assert result["rows"][0]["print_image_url"].startswith("/storage/sales-order-files/art.png?exp=")
        assert result["rows"][0]["batch_label"] == "Nastil 1"
        assert printing_board(db, offset=1, limit=1)["rows"] == []


def test_warehouse_remainders_distinct_shipments_real_dispatch_and_ranking():
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        packages = []
        for i, status in enumerate(["reserved", "received_in_storage", "packed"]):
            pack = Package(package_no=f"BOARD-P-{i}", barcode=f"BOARD-P-{i}", production_order_id=po.id,
                           model_id=po.model_id, color="blue", total_quantity=100,
                           dispatched_quantity=40 if i == 0 else 0, status=status, stock_kind="standard")
            db.add(pack)
            packages.append(pack)
        db.flush()
        for i, status, deleted in [(0, "shipped", None), (1, "draft", None), (2, "cancelled", None), (3, "delivered", STAMP)]:
            ship = Shipment(shipment_no=f"BOARD-S-{i}", status=status, shipped_at=STAMP, deleted_at=deleted)
            db.add(ship)
            db.flush()
            for pack in packages[:2]:
                db.add(ShipmentPackage(shipment_id=ship.id, package_id=pack.id, quantity=20))
        db.commit()
        result = warehouse_board(db, DAY, DAY)
        assert result["inventory_packages"] == 2
        assert result["inventory_pieces"] == 160
        assert result["shipment_count"] == 1
        assert result["shipped_packages"] == 2 and result["shipped_pieces"] == 40
        assert result["hot_products"][0]["shipped_pieces"] == 40
        assert warehouse_board(db, DAY, DAY, stock_kind="first_grade")["inventory_pieces"] == 0


@pytest.mark.parametrize("path", ["cutting?start=2026-01-02&end=2026-01-02", "printing", "warehouse?start=2026-01-02&end=2026-01-02"])
def test_board_authentication(client, path):
    assert client.get("/api/dashboard/" + path).status_code == 401


def test_board_validation_and_permission_boundaries(client, auth_headers):
    assert client.get("/api/dashboard/cutting?start=2026-01-03&end=2026-01-02", headers=auth_headers).status_code == 422
    assert client.get("/api/dashboard/printing?offset=-1", headers=auth_headers).status_code == 422
    assert client.get("/api/dashboard/warehouse?start=2026-01-02&end=2026-01-02&stock_kind=bad", headers=auth_headers).status_code == 422
    assert client.get("/api/dashboard/cutting?start=2026-01-02&end=2026-01-02&cutting_department_code=ECT", headers=auth_headers).status_code == 403
    from app.core.deps import get_current_user
    from app.main import app
    from app.schemas import Role, User
    viewer = User(id=9999, name="Viewer", email="board-viewer@example.com", is_active=True,
                  role=Role(name="Viewer", permissions=["sales.orders"]), factory_code="MIL")
    app.dependency_overrides[get_current_user] = lambda: viewer
    try:
        for path in ["printing", "cutting?start=2026-01-02&end=2026-01-02", "warehouse?start=2026-01-02&end=2026-01-02"]:
            assert client.get("/api/dashboard/" + path).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_boards_do_not_write_business_data():
    from app.db.base import Base
    with TestSessionLocal() as db:
        po, wo, rec = order(db)
        bundle(db, po, rec, "BOARD-READ-ONLY", next_dept="PRT")
        db.commit()
        def fingerprint():
            return {t.name: sorted(repr(tuple(r)) for r in db.execute(select(t))) for t in Base.metadata.sorted_tables}
        before = fingerprint()
        cutting_board(db, "CUT", DAY, DAY)
        printing_board(db)
        warehouse_board(db, DAY, DAY)
        assert fingerprint() == before
