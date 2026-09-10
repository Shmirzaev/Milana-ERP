"""Explicitly requested routing and completed-cut corrections; dry-run by default."""
import argparse
import json

from sqlalchemy import text
from app.db.session import SessionLocal
from app.models import Bundle, CuttingRecord, Department, ProductionOrder, User, WorkOrder
from app.core.deps import is_super_admin
from app.services.audit import log_action
from app.api.routes.production import complete_cutting_with_shortage, _ensure_replacements_do_not_block_completion


def run(apply=False):
    reroute = {"PO-0148": (170, 658), "PO-0152": (174, 674)}
    close = {"PO-0150": (172, 666, 498), "PO-0153": (175, 678, 588), "PO-0154": (176, 682, 366)}
    with SessionLocal() as db:
        db.execute(text("SET LOCAL lock_timeout='5s'"))
        db.execute(text("SET LOCAL statement_timeout='30s'"))
        pos = db.query(ProductionOrder).filter(ProductionOrder.id.in_([170, 172, 174, 175, 176])).order_by(ProductionOrder.id).with_for_update().all()
        assert {p.production_no for p in pos} == set(reroute) | set(close)
        works = db.query(WorkOrder).filter(WorkOrder.production_order_id.in_([p.id for p in pos])).order_by(WorkOrder.id).with_for_update().all()
        by_id = {w.id: w for w in works}
        depts = {d.code: d.id for d in db.query(Department).all()}
        def snapshot():
            return {w.id: {column.name: getattr(w, column.name) for column in WorkOrder.__table__.columns} for w in works}
        def physical():
            result = {}
            for table,field,ids in (("bundles", "production_order_id", "170,172,174,175,176"), ("cutting_records", "work_order_id", "658,666,674,678,682")):
                result[table] = db.execute(text(f"select md5(coalesce(jsonb_agg(to_jsonb(t) order by id)::text,'')) from {table} t where {field} in ({ids})")).scalar_one()
            return result
        before = snapshot()
        physical_before = physical()
        for number,(po_id,wid) in reroute.items():
            po = next(p for p in pos if p.id == po_id)
            w = by_id[wid]
            assert po.production_no == number and po.status == "planning" and po.source_type == "standard"
            assert w.production_order_id == po_id and w.operation == "cutting" and w.department_id == depts["ECT"] and w.status == "waiting"
            assert w.passed_qty == w.actual_output_qty == w.failed_qty == 0
            assert not db.query(CuttingRecord.id).filter(CuttingRecord.work_order_id == wid).first()
            assert not db.query(Bundle.id).filter(Bundle.production_order_id == po_id).first()
            sew = next(x for x in works if x.production_order_id == po_id and x.operation == "sewing")
            assert sew.department_id == depts["BST"] and sew.status == "waiting"
        for number,(po_id,wid,qty) in close.items():
            po = next(p for p in pos if p.id == po_id)
            w = by_id[wid]
            assert po.production_no == number and po.source_type == "standard"
            assert w.production_order_id == po_id and w.operation == "cutting" and w.department_id == depts["CUT"] and w.status == "in_progress"
            assert w.planned_output_qty == 600 and w.passed_qty == w.actual_output_qty == qty and w.failed_qty == 0
            records = db.query(CuttingRecord).filter(CuttingRecord.work_order_id == wid).all()
            assert len(records) == 1 and records[0].passed_pieces == qty and records[0].defective_pieces == 0
            _ensure_replacements_do_not_block_completion(db, w)
        report = {"apply": apply, "reroute": reroute, "complete": close, "physical_before": physical_before}
        if not apply:
            return report
        actor = next(u for u in db.query(User).order_by(User.id).all() if u.is_active and is_super_admin(u))
        # Keep the existing endpoint's commits inside this one guarded transaction.
        commit = db.commit
        db.commit = db.flush
        for number,(_,wid) in reroute.items():
            w = by_id[wid]
            w.department_id = depts["CUT"]
            log_action(db, actor, "correct_cutting_department", "WorkOrder", wid, old_value={"department":"ECT"}, new_value={"department":"CUT", "sewing_factory":"BST", "production_no":number, "reason":"Explicit user correction 2026-09-10"})
        for _,wid,_ in close.values():
            complete_cutting_with_shortage(wid, db, actor)
        db.flush()
        assert physical() == physical_before
        after = snapshot()
        allowed_close = {"status", "actual_input_qty", "actual_output_qty", "passed_qty", "failed_qty", "start_time", "end_time", "updated_at"}
        for wid,old in before.items():
            changed = {key for key in old if old[key] != after[wid][key]}
            allowed = {"department_id", "updated_at"} if wid in (658,674) else allowed_close if wid in (666,678,682) else set()
            assert changed <= allowed, (wid, changed)
        report["changed"] = {wid:{k:{"before":before[wid][k],"after":after[wid][k]} for k in before[wid] if before[wid][k]!=after[wid][k]} for wid in before if before[wid]!=after[wid]}
        assert set(report["changed"]) == {658,666,674,678,682}
        commit()
        report["committed"] = True
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.apply), default=str, indent=2))
