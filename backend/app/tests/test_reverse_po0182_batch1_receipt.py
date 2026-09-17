import pytest

from app.db.session import SessionLocal
from app.models import Bundle, BundleScanLog, ProductionBatch, ProductionOrder, WorkOrder
from scripts.reverse_po0182_batch1_receipt import EXTRA_IDS, FIRST_IDS, correct, snapshot


def seed_target(db):
    db.add(ProductionOrder(id=204, production_no="PO-0182", model_id=5459,
                           production_type="branded_stock", planned_quantity=900, status="sewing"))
    db.add(WorkOrder(id=796, production_order_id=204, operation="sewing", department_id=8,
                     status="in_progress", planned_input_qty=960, planned_output_qty=960, actual_input_qty=960))
    for bid, label, quantity in ((89, "0204-01", 450), (95, "0204-02", 510)):
        db.add(ProductionBatch(id=bid, production_order_id=204, batch_no=label, batch_index=1 if bid == 89 else 2,
                               planned_quantity=quantity))
    for i, bid in enumerate(FIRST_IDS + EXTRA_IDS):
        db.add(Bundle(id=bid, production_order_id=204, production_batch_id=89 if i < 6 else 95,
                      model_id=5459, bundle_no=f"TEST-{bid}", barcode=f"TEST-{bid}",
                      quantity=75 if i < 6 else 85, sewing_factory_code="BST", color="black", size="M",
                      status="received_sewing", current_department_id=8, next_department_id=8))
        db.add(BundleScanLog(id=3053+i, bundle_id=bid, scan_type="created", to_department_id=4))
        db.add(BundleScanLog(id=3242+i, bundle_id=bid, scan_type="received_sewing", from_department_id=4, to_department_id=8))
    db.commit()


def test_reverse_one_batch_keeps_extra_and_history_then_retry():
    with SessionLocal() as db:
        seed_target(db)
        extra_before = [snapshot(db.get(Bundle, bid)) for bid in EXTRA_IDS]
        assert correct(db)["status"] == "ready"
        assert db.get(Bundle, FIRST_IDS[0]).status == "received_sewing"
        assert correct(db, apply=True)["status"] == "applied"
        db.commit()
        assert [snapshot(db.get(Bundle, bid)) for bid in EXTRA_IDS] == extra_before
        assert all(db.get(Bundle, bid).status == "created" for bid in FIRST_IDS)
        assert db.get(WorkOrder, 796).actual_input_qty == 510
        assert db.get(WorkOrder, 796).planned_output_qty == 960
        assert db.query(BundleScanLog).filter_by(scan_type="received_sewing").count() == 12
        assert db.query(BundleScanLog).filter_by(scan_type="receive_sewing_reversed").count() == 6
        assert correct(db, apply=True)["status"] == "already_applied"


@pytest.mark.parametrize("change", ["quantity", "output", "extra", "history"])
def test_reversal_stops_when_evidence_changes(change):
    with SessionLocal() as db:
        seed_target(db)
        if change == "quantity":
            db.get(Bundle, FIRST_IDS[0]).quantity += 1
        elif change == "output":
            db.get(WorkOrder, 796).actual_output_qty = 1
        elif change == "extra":
            db.get(Bundle, EXTRA_IDS[0]).status = "created"
        else:
            db.add(BundleScanLog(bundle_id=FIRST_IDS[0], scan_type="changed"))
        db.commit()
        with pytest.raises(RuntimeError):
            correct(db, apply=True)
        db.rollback()
        assert all(db.get(Bundle, bid).status == "received_sewing" for bid in FIRST_IDS)
        assert db.get(WorkOrder, 796).actual_input_qty == 960


def test_reversal_rolls_back_atomically():
    with SessionLocal() as db:
        seed_target(db)
        correct(db, apply=True)
        db.rollback()
        assert all(db.get(Bundle, bid).status == "received_sewing" for bid in FIRST_IDS)
        assert db.get(WorkOrder, 796).actual_input_qty == 960
        assert db.query(BundleScanLog).filter_by(scan_type="receive_sewing_reversed").count() == 0
