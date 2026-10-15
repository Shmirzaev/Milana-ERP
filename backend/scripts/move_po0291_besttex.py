"""Owner-requested routing correction; defaults to a read-only preview."""
import argparse
import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.models import Bundle, Department, Package, PayrollQrLabel, ProductionOrder, SewingAssignment, SewingRecord, User, WorkOrder
from app.services.audit import log_action
from app.services.bundles import sync_textile_departments_for_bundle_route


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor-id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        if not args.apply:
            db.execute(text("SET TRANSACTION READ ONLY"))
        orders = db.query(ProductionOrder).filter_by(production_no="PO-0291")
        po = (orders.with_for_update() if args.apply else orders).one()
        assert po.id == 316 and po.planned_quantity == 600
        work_query = db.query(WorkOrder).filter_by(production_order_id=po.id).order_by(WorkOrder.id)
        works = (work_query.with_for_update() if args.apply else work_query).all()
        bundle_query = db.query(Bundle).filter_by(production_order_id=po.id).order_by(Bundle.id)
        bundles = (bundle_query.with_for_update() if args.apply else bundle_query).all()
        departments = {d.code: d for d in db.query(Department).filter(Department.code.in_(["MIL", "BST", "PKG", "BPK", "CUT"]))}
        assert len(bundles) == 5 and sum(b.quantity for b in bundles) == 400
        assert not db.query(SewingRecord).filter(SewingRecord.work_order_id.in_([w.id for w in works])).first()
        assert not db.query(SewingAssignment).filter(SewingAssignment.work_order_id.in_([w.id for w in works])).first()
        assert not db.query(Package).filter_by(production_order_id=po.id).first()
        assert not db.query(PayrollQrLabel.id).filter_by(production_order_id=po.id).first()
        assert all(w.actual_output_qty == 0 for w in works if w.operation in {"sewing", "packaging"})
        assert all(b.status == "created" and b.current_department_id == departments["CUT"].id for b in bundles)

        def snapshot():
            return {"production_no": po.production_no, "status": po.status,
                    "work_orders": [{"id": w.id, "operation": w.operation, "department_id": w.department_id,
                                     "status": w.status, "actual_output_qty": w.actual_output_qty} for w in works],
                    "bundles": [{"id": b.id, "quantity": b.quantity, "factory": b.sewing_factory_code,
                                 "next_department_id": b.next_department_id} for b in bundles]}

        before = snapshot()
        if args.apply:
            assert args.actor_id, "An audit actor is required"
            actor = db.get(User, args.actor_id)
            assert actor and actor.is_active
            assert all(b.sewing_factory_code in {"MIL", "BST"} for b in bundles)
            for bundle in bundles:
                bundle.sewing_factory_code = "BST"
                bundle.next_department_id = departments["BST"].id
            db.flush()
            assert sync_textile_departments_for_bundle_route(db, po.id) == ("BST", "BPK")
            after = snapshot()
            log_action(db, actor, "move_sewing_to_besttex", "ProductionOrder", po.id,
                       old_value=before, new_value={**after, "reason": "Owner requested PO-0291 be sewn at Besttex"})
            db.commit()
            print(json.dumps({"applied": True, "before": before, "after": after}))
        else:
            print(json.dumps({"applied": False, "before": before, "target": {"sewing": "BST", "packaging": "BPK"}}))


if __name__ == "__main__":
    main()
