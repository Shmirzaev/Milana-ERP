from pathlib import Path
import runpy

from app.schemas import Department, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def test_exact_six_unstarted_orders_change_only_cutting_department(client, auth_headers):
    repair = runpy.run_path(str(Path(__file__).parents[2] / "scripts/reassign_po_cutting_20261019.py"))
    with TestSessionLocal() as db:
        departments = dict(db.query(Department.code, Department.id).all())
        sewing_ids = []
        for number in repair["ORDER_NUMBERS"]:
            po = ProductionOrder(production_no=number, model_id=1, production_type="branded_stock", planned_quantity=600)
            db.add(po); db.flush()
            db.add(WorkOrder(production_order_id=po.id, department_id=departments["CUT"], operation="cutting", status="waiting"))
            sewing = WorkOrder(production_order_id=po.id, department_id=departments["BST"], operation="sewing", status="waiting")
            db.add(sewing); db.flush(); sewing_ids.append(sewing.id)
        db.commit()
        changed = repair["reassign"](db, backup="/opt/milana-erp/shared/backups/test.dump")
        assert len(changed) == 6
        db.commit()
        assert all(db.get(WorkOrder, wid).department_id == departments["BST"] for wid in sewing_ids)
        assert all(db.get(WorkOrder, wid).department_id == departments["ECT"] for _, wid, _ in changed)
        assert repair["reassign"](db, backup="/opt/milana-erp/shared/backups/test.dump") == []
