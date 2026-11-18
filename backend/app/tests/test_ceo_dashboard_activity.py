from datetime import date, datetime, time, timedelta, timezone

from app.libs.dto.ceo_dashboard.report import DateBucket, PackPieces, ReportWindow
from app.libs.enums.ceo_dashboard import FactoryFilter, ReportGrouping
from app.models.ceo_dashboard_activity_service import read_activity
from app.schemas import (
    CuttingRecord, Department, LegacyStockReceipt, ManualPackageReceipt, Model, Package, PackageChangeRequest,
    PackagingRecord, PrintingRecord, ProductionOrder, SewingFlow, SewingRecord, Shipment, ShipmentPackage, User,
    WorkOrder,
)
from app.schemas.fulfillment.shipment_review import PackageQuantityAdjustment
from app.schemas.production.sewing_daily_report import SewingDailyReport
from app.tests.conftest import TestSessionLocal


SUNDAY = date(2020, 1, 5)
MONDAY = SUNDAY + timedelta(days=1)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = TUESDAY + timedelta(days=1)


def _stamp(day, hour=0, minute=0):
    # The test dates use Tashkent UTC+5.
    return datetime.combine(day, time(hour, minute), timezone.utc) - timedelta(hours=5)


def _window(factory=FactoryFilter.ALL, *, weekly=False):
    now = _stamp(TUESDAY, 12)
    buckets = (
        (DateBucket(start=SUNDAY, end=SUNDAY), DateBucket(start=MONDAY, end=TUESDAY))
        if weekly else tuple(DateBucket(start=day, end=day) for day in (SUNDAY, MONDAY, TUESDAY))
    )
    return ReportWindow(
        start=SUNDAY, end=TUESDAY, lower=_stamp(SUNDAY), upper=now, as_of=now, factory=factory,
        grouping=ReportGrouping.WEEKLY if weekly else ReportGrouping.DAILY, buckets=buckets,
    )


def _order(db, label):
    order = ProductionOrder(production_no=label, model_id=db.query(Model.id).first()[0],
                            production_type="branded_stock")
    db.add(order)
    db.flush()
    return order


def _work(db, order, operation, code):
    department = db.query(Department).filter_by(code=code).first()
    if not department:
        department = Department(code=code, name=code)
        db.add(department)
        db.flush()
    work = WorkOrder(production_order_id=order.id, department_id=department.id, operation=operation)
    db.add(work)
    db.flush()
    return work.id


def _pack(db, label, *, order=None, department="PKG", quantity=80, **fields):
    package = Package(
        package_no=label, barcode=label, total_quantity=quantity, capacity=quantity, color="Blue",
        production_order_id=order.id if order else None, packaging_department_code=department, **fields,
    )
    db.add(package)
    db.flush()
    return package


def _dispatch(db, label, stamp, packages=(), **fields):
    shipment = Shipment(shipment_no=label, shipped_at=stamp, **fields)
    db.add(shipment)
    db.flush()
    for pack, quantity in packages:
        db.add(ShipmentPackage(shipment_id=shipment.id, package_id=pack.id, quantity=quantity))
    db.flush()
    return shipment


def test_production_approval_date_passed_pieces_and_factory_comparison():
    with TestSessionLocal() as db:
        order = _order(db, "CEO-STAGE")
        cutting = _work(db, order, "cutting", "CUT")
        printing = _work(db, order, "printing", "PRT")
        sewing = _work(db, order, "sewing", "BST")
        packing = _work(db, order, "packaging", "ECP")
        other = _work(db, _order(db, "CEO-UNKNOWN-DEPT"), "cutting", "NEW")
        flow = SewingFlow(factory_code="BST", name="CEO sewing line", code="CEO-LINE")
        db.add(flow)
        db.flush()
        db.add_all([
            CuttingRecord(work_order_id=cutting, created_at=_stamp(SUNDAY, 23, 59), passed_pieces=10,
                          cut_pieces=15, approved_at=_stamp(MONDAY)),
            CuttingRecord(work_order_id=cutting, created_at=_stamp(MONDAY) - timedelta(microseconds=1),
                          passed_pieces=3, cut_pieces=3),
            CuttingRecord(work_order_id=cutting, created_at=_stamp(MONDAY), passed_pieces=100, approval_status="pending"),
            CuttingRecord(work_order_id=cutting, created_at=_stamp(MONDAY), passed_pieces=100, approval_status="rejected"),
            CuttingRecord(work_order_id=other, created_at=_stamp(TUESDAY), passed_pieces=2, cut_pieces=2),
            PrintingRecord(work_order_id=printing, created_at=_stamp(MONDAY), passed_qty=8, printed_qty=10),
            SewingRecord(work_order_id=sewing, created_at=_stamp(MONDAY), passed_qty=7, sewn_qty=8),
            PackagingRecord(work_order_id=packing, created_at=_stamp(TUESDAY, 11, 59), packed_qty=6),
            PackagingRecord(work_order_id=packing, created_at=_stamp(TUESDAY, 12), packed_qty=99),
            SewingDailyReport(report_date=MONDAY, sewing_flow_id=flow.id, work_order_id=sewing, sewn_qty=100,
                              line_code=flow.code, line_name=flow.name),
        ])
        db.flush()
        result = read_activity(db, _window(FactoryFilter.BST, weekly=True))

        first, second = result.buckets
        assert (first.start, first.end, second.start, second.end) == (SUNDAY, SUNDAY, MONDAY, TUESDAY)
        assert {(row.factory, row.department, row.stage, row.pieces) for row in first.output} == {
            ("MIL", "CUT", "cutting", 3),
        }
        assert {(row.factory, row.department, row.stage, row.pieces) for row in second.output} == {
            ("MIL", "CUT", "cutting", 10),
            ("MIL", "PRT", "printing", 8),
            ("BST", "BST", "sewing", 7),
            ("ECO", "ECP", "packaging", 6),
            ("UNASSIGNED", "NEW", "cutting", 2),
        }
        assert first.finished_receipts == second.finished_receipts == PackPieces()
        assert first.shipments == second.shipments == PackPieces()
        assert not db.dirty and not db.new and not db.deleted


def test_receipts_separate_migration_unproven_origin_and_confirmed_additions():
    with TestSessionLocal() as db:
        order = _order(db, "CEO-RECEIVE")
        _work(db, order, "packaging", "BPK")
        user_id = db.query(User.id).first()[0]
        legacy = LegacyStockReceipt(
            source_system="CEO", source_warehouse_id="warehouse", source_record_id="legacy-pack",
            source_checksum="0" * 64, source_payload={}, imported_at=_stamp(TUESDAY),
        )
        warehouse_receipt = ManualPackageReceipt(receipt_no="CEO-MANUAL-RECEIVE", created_by=user_id,
                                                  evidence={}, evidence_hash="0" * 64)
        packaging_receipt = ManualPackageReceipt(
            receipt_no="CEO-MANUAL-PACK", created_by=user_id,
            evidence={"source": "manual_packaging", "packaging_department_code": "ECP"}, evidence_hash="1" * 64,
        )
        db.add_all((legacy, warehouse_receipt, packaging_receipt))
        db.flush()
        corrected = _pack(db, "CEO-INTAKE", order=order, department="BPK", quantity=30,
                          status="shipped", received_at=_stamp(MONDAY), dispatched_quantity=21)
        _pack(db, "CEO-UNRECEIVED", order=order, department="BPK", status="packed")
        _pack(db, "CEO-MIGRATED", legacy_receipt_id=legacy.id, quantity=61,
              status="received_in_storage", received_at=_stamp(MONDAY))
        _pack(db, "CEO-MANUAL-WAREHOUSE", manual_receipt_id=warehouse_receipt.id, quantity=17,
              status="received_in_storage", received_at=_stamp(MONDAY))
        _pack(db, "CEO-MANUAL-PACKAGING", manual_receipt_id=packaging_receipt.id, department="ECP", quantity=12,
              status="received_in_storage", received_at=_stamp(TUESDAY))
        # Old PKG default has no corroborating Packaging work order.
        _pack(db, "CEO-UNPROVEN", order=order, quantity=5, status="received_in_storage", received_at=_stamp(MONDAY))
        _pack(db, "CEO-FUTURE-RECEIPT", order=order, department="BPK", status="received_in_storage",
              received_at=_stamp(TUESDAY, 12))
        changed = _pack(db, "CEO-EDIT", order=order, department="BPK", quantity=6,
                        status="received_in_storage", received_at=_stamp(MONDAY))
        shipment = _dispatch(db, "CEO-INTAKE-DRAFT", None)
        db.add_all([
            PackageQuantityAdjustment(
                package_id=corrected.id, shipment_id=shipment.id, delta=10, before_json={"quantity": 20},
                after_json={"quantity": 30}, reason="Confirmed additional stock", created_by=user_id,
                created_at=_stamp(TUESDAY, 1), extra_receipt_quantity=10,
            ),
            PackageChangeRequest(
                package_id=changed.id, package_no=changed.package_no, request_type="edit", status="approved",
                before_json={"total_quantity": 7}, payload_json={"total_quantity": 6},
                reviewed_at=_stamp(TUESDAY),
            ),
        ])
        db.flush()
        _, monday, tuesday = read_activity(db, _window()).buckets
        assert monday.finished_receipts == PackPieces(packs=4, pieces=49)
        assert monday.receipts_unassigned == PackPieces(packs=2, pieces=22)
        assert monday.legacy_imports == PackPieces()
        assert tuesday.finished_receipts == PackPieces(packs=1, pieces=22)
        assert tuesday.legacy_imports == PackPieces(packs=1, pieces=61)
        _, bst_monday, bst_tuesday = read_activity(db, _window(FactoryFilter.BST)).buckets
        assert bst_monday.finished_receipts == PackPieces(packs=2, pieces=27)
        assert bst_monday.receipts_unassigned == monday.receipts_unassigned
        assert bst_tuesday.finished_receipts == PackPieces(packs=0, pieces=10)


def test_shipments_count_a_partial_pack_per_dispatch_and_use_frozen_evidence():
    with TestSessionLocal() as db:
        order = _order(db, "CEO-DISPATCH")
        _work(db, order, "packaging", "ECP")
        pack = _pack(db, "CEO-PARTIAL", order=order, department="ECP", status="shipped", dispatched_quantity=78)
        _dispatch(
            db, "CEO-SHIP-1", _stamp(SUNDAY, 23, 59), [(pack, 77)], status="shipped",
            dispatch_snapshot={"document": {
                "package_details": [{"package_no": pack.package_no, "quantity": 18}],
                "lines": [{"package_no": pack.package_no, "quantity": 120}],
            }},
        )
        _dispatch(
            db, "CEO-SHIP-2", _stamp(MONDAY), [(pack, 77)], status="delivered",
            delivered_at=_stamp(WEDNESDAY), dispatch_snapshot={"document": {"lines": [
                {"package_no": pack.package_no, "quantity": 6},
                {"package_no": pack.package_no, "quantity": 8},
                {"package_no": "retired-label", "quantity": 5},
            ]}},
        )
        _dispatch(db, "CEO-SHIP-3", _stamp(MONDAY, 1), [(pack, 7)], status="shipped")
        _dispatch(db, "CEO-REOPENED", None, [(pack, 2)], status="created")
        _dispatch(db, "CEO-CANCELLED", _stamp(MONDAY), [(pack, 3)], status="cancelled")
        _dispatch(db, "CEO-VOID", _stamp(MONDAY), [(pack, 4)], status="shipped", deleted_at=_stamp(MONDAY, 1))
        _dispatch(db, "CEO-MISSING-DATE", None, [(pack, 2)], status="shipped")
        _dispatch(db, "CEO-FUTURE-DISPATCH", _stamp(TUESDAY, 12), [(pack, 1)], status="shipped")
        sunday, monday, tuesday = read_activity(db, _window()).buckets

        assert sunday.shipments == PackPieces(packs=1, pieces=18)
        assert monday.shipments == PackPieces(packs=3, pieces=26)
        assert monday.shipments_unassigned == PackPieces(packs=1, pieces=5)
        assert tuesday.shipments == PackPieces()
        _, eco_monday, _ = read_activity(db, _window(FactoryFilter.ECO)).buckets
        assert eco_monday.shipments == PackPieces(packs=2, pieces=21)
        assert eco_monday.shipments_unassigned == monday.shipments_unassigned
