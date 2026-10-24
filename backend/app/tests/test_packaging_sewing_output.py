"""Packaging consumes passed Sewing evidence, never the Cutting/order plan."""
import pytest

from app.schemas import Department, PackagingReceipt, PackagingRecord, SewingRecord, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_production_flow import _issue_required_accessories


def _create(client, headers, *, batched=True):
    payload = {
        "production_type": "branded_stock", "model_id": 1, "planned_quantity": 600,
        "items": [{"model_id": 1, "color": "white", "size": "M", "planned_quantity": 600}],
    }
    if batched:
        payload["batches"] = [{"name": "Nastil 1", "planned_quantity": 600}]
    response = client.post("/api/planning/create-branded-production", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    po = client.get(f"/api/production-orders/{response.json()['id']}", headers=headers).json()
    return po, {w["operation"]: w["id"] for w in po["work_orders"]}, po["batches"][0]["id"] if batched else None


def _pack(client, headers, wid, bid, quantity, packed=None):
    return client.post("/api/packaging/records", headers=headers, json={
        "work_order_id": wid, "production_batch_id": bid, "input_qty": quantity,
        "packed_qty": quantity if packed is None else packed,
        "damaged_qty": 0 if packed is None else quantity - packed,
    })


@pytest.mark.parametrize("batched", [False, True])
def test_actual_tracks_cutting_sewing_packaging_and_limits_partial_input(client, auth_headers, batched):
    po, work, bid = _create(client, auth_headers, batched=batched)
    oid = po["id"]
    assert po["actual_quantity"] == 0
    response = client.post("/api/cutting/records", headers=auth_headers, json={
        "work_order_id": work["cutting"], "production_batch_id": bid,
        "input_quantity": 20, "input_unit": "kg", "cut_pieces": 600,
        "passed_pieces": 590, "defective_pieces": 10, "waste_quantity": 0, "waste_unit": "kg",
        "bundles": [{"color": "white", "size": "M", "quantity": 590, "count": 1}],
    })
    assert response.status_code == 201, response.text

    def actual(expected):
        detail = client.get(f"/api/production-orders/{oid}", headers=auth_headers).json()
        assert detail["actual_quantity"] == expected
        assert detail["planned_quantity"] == 600
        rows = client.get("/api/process-tracking", headers=auth_headers, params={"q": po["production_no"]}).json()
        row = next(r for r in rows if r["production_order_id"] == oid)
        assert row["actual_quantity"] == expected
        if bid:
            assert row["batches"][0]["actual_quantity"] == expected

    actual(590)
    assert _pack(client, auth_headers, work["packaging"], bid, 1).status_code == 400
    _issue_required_accessories(client, auth_headers, oid)
    response = client.post("/api/sewing/records", headers=auth_headers, json={
        "work_order_id": work["sewing"], "production_batch_id": bid,
        "input_qty": 590, "sewn_qty": 590, "passed_qty": 585, "failed_qty": 5,
        "size_quantities": [{"size": "M", "quantity": 585}],
    })
    assert response.status_code == 201, response.text
    actual(585)
    # An empty save must not replace real Sewing output with a fictitious zero.
    with TestSessionLocal() as db:
        db.add(PackagingRecord(work_order_id=work["packaging"], production_batch_id=bid,
                               input_qty=0, packed_qty=0, damaged_qty=0))
        db.commit()
    actual(585)

    def available(expected):
        response = client.get(f"/api/work-orders/{work['packaging']}/packaging-batch-progress", headers=auth_headers)
        assert response.status_code == 200, response.text
        progress = response.json()["items"][0] if bid else response.json()
        assert progress["sewing_output_qty"] == 585
        assert progress["available_input_qty"] == expected

    available(585)
    assert _pack(client, auth_headers, work["packaging"], bid, 590).status_code == 400
    response = _pack(client, auth_headers, work["packaging"], bid, 300, 298)
    assert response.status_code == 201, response.text
    available(285)
    actual(298)
    assert _pack(client, auth_headers, work["packaging"], bid, 286).status_code == 400
    response = _pack(client, auth_headers, work["packaging"], bid, 285, 284)
    assert response.status_code == 201, response.text
    available(0)
    actual(582)


@pytest.mark.parametrize("factory,department", [("MIL", "PKG"), ("BST", "BPK"), ("ECO", "ECP")])
@pytest.mark.parametrize("scoped", [False, True])
def test_sewing_budget_is_exact_batch_and_receipt_limited(client, auth_headers, factory, department, scoped):
    from app.core.security import create_access_token
    from app.schemas import ProductionBatch

    po, work, bid = _create(client, auth_headers)
    with TestSessionLocal() as db:
        sewing = db.get(WorkOrder, work["sewing"])
        packaging = db.get(WorkOrder, work["packaging"])
        sewing.department_id = db.query(Department.id).filter_by(code="SEW" if factory == "MIL" else factory).scalar()
        packaging.department_id = db.query(Department.id).filter_by(code=department).scalar()
        if scoped:
            sewing.production_batch_id = bid
            packaging.production_batch_id = bid
        other = ProductionBatch(production_order_id=po["id"], batch_no="OTHER", batch_index=2, planned_quantity=600)
        db.add(other)
        db.flush()
        db.add_all([
            SewingRecord(work_order_id=sewing.id, production_batch_id=None if scoped else bid,
                         input_qty=600, sewn_qty=600, passed_qty=590, failed_qty=10),
            SewingRecord(work_order_id=sewing.id, production_batch_id=other.id,
                         input_qty=600, sewn_qty=600, passed_qty=600),
            PackagingReceipt(work_order_id=packaging.id, source_work_order_id=sewing.id,
                             production_order_id=po["id"], production_batch_id=bid,
                             packaging_department_code=department, quantity=580, receive_method="manual"),
        ])
        db.commit()
    if factory != "MIL":
        assert _pack(client, auth_headers, work["packaging"], bid, 1).status_code == 403
    auth_headers = {"Authorization": f"Bearer {create_access_token(1, extra={'factory_code': factory})}"}
    response = client.get(f"/api/work-orders/{work['packaging']}/packaging-batch-progress", headers=auth_headers)
    assert response.status_code == 200, response.text
    progress = next(row for row in response.json()["items"] if row["id"] == bid)
    assert progress["sewing_output_qty"] == 590
    assert progress["available_input_qty"] == 580
    assert _pack(client, auth_headers, work["packaging"], bid, 581).status_code == 400
    response = _pack(client, auth_headers, work["packaging"], bid, 580)
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("loss_field", ["failed_qty", "rejected_qty"])
def test_zero_passed_sewing_and_correction_do_not_fall_back_to_plan(client, auth_headers, loss_field):
    po, work, bid = _create(client, auth_headers)
    with TestSessionLocal() as db:
        cutting = db.get(WorkOrder, work["cutting"])
        cutting.actual_output_qty = cutting.passed_qty = 590
        record = SewingRecord(work_order_id=work["sewing"], production_batch_id=bid,
                              input_qty=590, sewn_qty=590, passed_qty=585, failed_qty=5)
        db.add(record)
        db.commit()
        rid = record.id
    assert client.get(f"/api/production-orders/{po['id']}", headers=auth_headers).json()["actual_quantity"] == 585
    with TestSessionLocal() as db:
        record = db.get(SewingRecord, rid)
        record.passed_qty = 0
        record.failed_qty = 0
        setattr(record, loss_field, 590)
        db.commit()
    assert client.get(f"/api/production-orders/{po['id']}", headers=auth_headers).json()["actual_quantity"] == 0
    assert _pack(client, auth_headers, work["packaging"], bid, 1).status_code == 400
    rows = client.get("/api/process-tracking", headers=auth_headers, params={"q": po["production_no"]}).json()
    assert rows[0]["batches"][0]["actual_quantity"] == 0
