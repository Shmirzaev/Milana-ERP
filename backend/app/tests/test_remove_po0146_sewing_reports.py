from datetime import date

import pytest

from app.db.session import SessionLocal
from app.models import (
    AuditLog, Department, ProductionBatch, ProductionOrder, SewingAssignment,
    SewingDailyReport, SewingFlow, WorkOrder,
)
from scripts.remove_po0146_sewing_reports import REPORTS, correct


def seed_target(db):
    department = db.query(Department).filter_by(code="BST").one()
    db.add(ProductionOrder(id=168, production_no="PO-0146", production_type="branded_stock",
                           model_id=8046, planned_quantity=600, status="sewing"))
    db.add(SewingFlow(id=96, factory_code="BST", code="BST-BAND-01", name="Test line", is_active=True))
    db.flush()
    db.add(ProductionBatch(id=76, production_order_id=168, batch_no="0168-01", planned_quantity=600))
    db.add(WorkOrder(id=651, production_order_id=168, department_id=department.id,
                     operation="sewing", status="in_progress", sewing_flow_id=96))
    db.flush()
    db.add(SewingAssignment(id=34, work_order_id=651, sewing_flow_id=96,
                            production_batch_id=76, quantity=600, completed_qty=0, status="planned"))
    for rid, (sewn, defective, section) in REPORTS.items():
        db.add(SewingDailyReport(id=rid, production_order_id=168, work_order_id=651,
                                sewing_assignment_id=34, production_batch_id=76, sewing_flow_id=96,
                                report_date=date(2026, 9, 12), kroy_no="9049", line_code="BST-BAND-01",
                                line_name="Test line", sewn_qty=sewn, defective_qty=defective, section_no=section))
    db.add(SewingDailyReport(id=897, sewing_flow_id=96, report_date=date(2026, 9, 12),
                            line_code="BST-BAND-01", line_name="Test line", sewn_qty=10, defective_qty=0))
    db.commit()


def test_readonly_then_atomic_correction_preserves_order_and_other_report():
    with SessionLocal() as db:
        seed_target(db)
        assert correct(db)["status"] == "ready"
        assert db.query(SewingDailyReport).count() == 4
        assert db.get(SewingAssignment, 34).status == "planned"
        result = correct(db, apply=True)
        db.commit()
        assert result["returned_quantity"] == 600
        assert db.query(SewingDailyReport).one().id == 897
        assert db.get(ProductionOrder, 168).status == "sewing"
        assert db.get(WorkOrder, 651).status == "in_progress"
        assert db.get(WorkOrder, 651).sewing_flow_id is None
        assert db.get(SewingAssignment, 34).status == "cancelled"
        audits = db.query(AuditLog).filter(AuditLog.id.in_(result["audit_ids"])).order_by(AuditLog.id).all()
        assert len(audits) == 4
        assert all(row.user_id is None for row in audits)
        assert audits[0].old_value_json["sewn_qty"] == 200
        assert audits[-1].old_value_json["assignment"]["status"] == "planned"
        assert all(b.prev_hash == a.entry_hash for a, b in zip(audits, audits[1:]))
        assert correct(db, apply=True)["status"] == "already_applied"


@pytest.mark.parametrize("change", ["quantity", "output", "work_output", "additional_report", "factory"])
def test_changed_evidence_blocks_entire_correction(change):
    with SessionLocal() as db:
        seed_target(db)
        if change == "quantity":
            db.get(SewingDailyReport, 894).sewn_qty += 1
        elif change == "output":
            db.get(SewingAssignment, 34).completed_qty = 1
        elif change == "factory":
            db.get(SewingFlow, 96).factory_code = "MIL"
        elif change == "work_output":
            db.get(WorkOrder, 651).actual_output_qty = 1
        else:
            db.get(SewingDailyReport, 897).production_order_id = 168
        db.commit()
        with pytest.raises(RuntimeError):
            correct(db, apply=True)
        db.rollback()
        assert db.query(SewingDailyReport).count() == 4
        assert db.get(SewingAssignment, 34).status == "planned"


def test_rollback_restores_reports_assignment_and_audit():
    with SessionLocal() as db:
        seed_target(db)
        before_audits = db.query(AuditLog).count()
        correct(db, apply=True)
        db.rollback()
        assert db.query(SewingDailyReport).count() == 4
        assert db.get(SewingAssignment, 34).status == "planned"
        assert db.get(WorkOrder, 651).sewing_flow_id == 96
        assert db.query(AuditLog).count() == before_audits
