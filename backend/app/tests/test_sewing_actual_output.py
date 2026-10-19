from uuid import uuid4

import pytest

from app.models import CuttingRecord, Department, Model, ProductionBatch, ProductionOrder, SewingRecord, WorkOrder
from app.services.audit import log_action
from app.tests.conftest import TestSessionLocal


def make_batch(*, plan=235, cut=225, printing=False):
    with TestSessionLocal() as db:
        model = Model(code=f"ACTUAL-{uuid4().hex[:8]}", name="Actual output", product_type="shirt")
        db.add(model); db.flush()
        po = ProductionOrder(production_no=f"PO-ACTUAL-{uuid4().hex[:8]}", model_id=model.id,
                             production_type="branded_stock", source_type="standard", planned_quantity=225)
        db.add(po); db.flush()
        batch = ProductionBatch(production_order_id=po.id, batch_no=f"{po.id:04d}-01", batch_index=1, planned_quantity=plan)
        db.add(batch); db.flush()
        orders = {}
        for operation, code in [("cutting", "CUT"), ("sewing", "SEW"), ("packaging", "PKG")]:
            wo = WorkOrder(production_order_id=po.id, operation=operation,
                           department_id=db.query(Department.id).filter_by(code=code).scalar(),
                           status="in_progress", planned_input_qty=225, planned_output_qty=225,
                           passed_qty=cut if operation == "cutting" else 0)
            db.add(wo); db.flush(); orders[operation] = wo.id
        if cut:
            db.add(CuttingRecord(work_order_id=orders["cutting"], production_batch_id=batch.id,
                                 cut_pieces=cut, passed_pieces=cut, defective_pieces=0, input_quantity=0))
            if plan != cut:
                log_action(db, None, "update_cutting_batch", "ProductionBatch", batch.id,
                           old_value={"planned_quantity": cut}, new_value={"planned_quantity": plan})
        if printing:
            db.add(WorkOrder(production_order_id=po.id, operation="printing",
                             department_id=db.query(Department.id).filter_by(code="PRT").scalar(), status="waiting"))
        db.commit()
        return po.id, batch.id, orders


def sew(client, headers, batch, orders, input_qty, output):
    return client.post("/api/sewing/records", headers=headers, json={
        "work_order_id": orders["sewing"], "production_batch_id": batch,
        "input_qty": input_qty, "sewn_qty": output, "passed_qty": output,
    })


@pytest.mark.parametrize("input_qty", [225, 235])
def test_revised_nastil_and_overproduction_reach_packaging_and_actual(client, auth_headers, input_qty):
    po, batch, orders = make_batch()
    response = sew(client, auth_headers, batch, orders, input_qty, 250)
    assert response.status_code == 201, response.text
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, orders["sewing"]).passed_qty == 250
        assert db.get(WorkOrder, orders["packaging"]).planned_output_qty == 250
        assert db.query(CuttingRecord).filter_by(production_batch_id=batch).one().passed_pieces == 225
        assert db.query(SewingRecord).filter_by(production_batch_id=batch).one().input_qty == input_qty
    detail = client.get(f"/api/production-orders/{po}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["actual_quantity"] == 250
    tracked = client.get("/api/process-tracking", headers=auth_headers, params={
        "sewing_completed_only": "true", "include_total": "true", "q": detail.json()["production_no"],
    })
    assert tracked.status_code == 200, tracked.text
    process = next(row for row in tracked.json()["rows"] if row["production_order_id"] == po)
    assert process["sewing_completed_quantity"] == 250
    assert process["batches"][0]["sewing_completed_quantity"] == 250
    assert process["batches"][0]["sewing_unallocated_quantity"] == 250
    received = client.get("/api/packaging/receive-options", headers=auth_headers)
    row = next(row for row in received.json() if row["production_batch_id"] == batch)
    assert row["available_quantity"] == 250
    packed = client.post("/api/packaging/records", headers=auth_headers, json={
        "work_order_id": orders["packaging"], "production_batch_id": batch,
        "input_qty": 250, "packed_qty": 250, "damaged_qty": 0,
    })
    assert packed.status_code == 201, packed.text


def test_no_confirmed_cutting_and_duplicate_input_remain_blocked(client, auth_headers):
    _, batch, orders = make_batch(cut=0)
    assert sew(client, auth_headers, batch, orders, 235, 250).status_code == 400
    _, batch, orders = make_batch()
    assert sew(client, auth_headers, batch, orders, 235, 250).status_code == 201
    assert sew(client, auth_headers, batch, orders, 1, 1).status_code == 400


def test_printing_allowance_is_not_increased_by_nastil_plan(client, auth_headers):
    _, batch, orders = make_batch(printing=True)
    assert sew(client, auth_headers, batch, orders, 235, 250).status_code == 400


def test_standard_eco_cutting_can_revise_nastil(client, auth_headers):
    from app.tests.test_production_flow import _factory_headers
    _, batch, orders = make_batch()
    with TestSessionLocal() as db:
        db.get(WorkOrder, orders["cutting"]).department_id = db.query(Department.id).filter_by(code="ECT").scalar()
        db.commit()
    response = client.patch(f"/api/work-orders/{orders['cutting']}/batches/{batch}",
                            headers=_factory_headers("ECO"), json={"planned_quantity": 245})
    assert response.status_code == 200, response.text
    assert response.json()["planned_quantity"] == 245


def test_overproduction_record_can_be_corrected_without_rewriting_cutting(client, auth_headers):
    _, batch, orders = make_batch()
    response = sew(client, auth_headers, batch, orders, 225, 250)
    assert response.status_code == 201, response.text
    corrected = client.patch(f"/api/sewing/records/{response.json()['id']}", headers=auth_headers,
                             json={"expected_version": 0, "input_qty": 225, "sewn_qty": 260, "passed_qty": 260})
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["passed_qty"] == 260
