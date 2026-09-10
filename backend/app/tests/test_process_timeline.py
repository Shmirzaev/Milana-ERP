from uuid import uuid4

from app.models import Bundle, Department, ModelBOM, ProductionBatch, ProductionOrder, WorkOrder
from app.tests.conftest import TestSessionLocal


def test_timeline_receipt_requires_receive_and_stays_scoped_to_batch(client, auth_headers):
    suffix = uuid4().hex
    with TestSessionLocal() as db:
        db.query(ModelBOM).filter(ModelBOM.model_id == 1).delete(synchronize_session=False)
        cutting = db.query(Department).filter(Department.code == "CUT").one()
        sewing = db.query(Department).filter(Department.code == "MIL").one()
        po = ProductionOrder(production_no=f"TIMELINE-{suffix}", production_type="branded_stock",
                             model_id=1, planned_quantity=120, status="sewing")
        db.add(po)
        db.flush()
        batches = [ProductionBatch(production_order_id=po.id, batch_no=f"{suffix}-{i}",
                                   batch_index=i, planned_quantity=60) for i in (1, 2)]
        db.add_all(batches)
        db.flush()
        db.add(WorkOrder(production_order_id=po.id, department_id=cutting.id, operation="cutting",
                         status="completed", planned_output_qty=120, passed_qty=120, actual_output_qty=120))
        # Legacy input and in-progress flags alone must never turn acceptance green.
        db.add(WorkOrder(production_order_id=po.id, department_id=sewing.id, operation="sewing",
                         status="in_progress", planned_output_qty=120, actual_input_qty=999))
        bundles = [Bundle(bundle_no=f"TL-{suffix}-{i}", barcode=f"TL-{suffix}-{i}",
                          production_order_id=po.id, production_batch_id=batch.id,
                          model_id=1, color="white", size="M", quantity=60,
                          sewing_factory_code="MIL", status="sent_to_sewing",
                          current_department_id=cutting.id, next_department_id=sewing.id)
                   for i, batch in enumerate(batches)]
        db.add_all(bundles)
        db.commit()
        production_no, bundle_id = po.production_no, bundles[0].id
        batch_ids = [batch.id for batch in batches]

    def snapshot():
        response = client.get(f"/api/process-tracking?q={production_no}", headers=auth_headers)
        assert response.status_code == 200, response.text
        return next(row for row in response.json() if row["production_no"] == production_no)

    before = snapshot()
    before_sewing = next(stage for stage in before["stages"] if stage["operation"] == "sewing")
    assert before_sewing["received_qty"] == 0
    assert before_sewing["output_qty"] == 0
    receipt = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert receipt.status_code == 200, receipt.text
    after = snapshot()
    stage = next(stage for stage in after["stages"] if stage["operation"] == "sewing")
    assert stage["received_qty"] == 60
    assert stage["completed"] == stage["output_qty"] == 0
    received_by_batch = {batch["id"]: next(s for s in batch["stages"] if s["operation"] == "sewing")["received_qty"]
                         for batch in after["batches"]}
    assert received_by_batch == {batch_ids[0]: 60, batch_ids[1]: 0}
    duplicate = client.post(f"/api/bundles/{bundle_id}/receive-sewing", headers=auth_headers)
    assert duplicate.status_code == 409
    assert next(s for s in snapshot()["stages"] if s["operation"] == "sewing")["received_qty"] == 60
