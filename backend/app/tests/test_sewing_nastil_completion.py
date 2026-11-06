"""Sewing completion accounts for every nastil while retaining real shortages."""
from datetime import datetime, timezone

import pytest

from app.core.security import create_access_token
from app.schemas import Bundle, Department, ProductionBatch, SewingAssignment, SewingFlow, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_sewing_output import _create, _pack
from app.tests.test_production_flow import _issue_required_accessories


def _sew(client, headers, wid, bid, quantity, assignment_id=None):
    return client.post("/api/sewing/records", headers=headers, json={
        "work_order_id": wid, "production_batch_id": bid,
        "sewing_assignment_id": assignment_id,
        "input_qty": quantity, "sewn_qty": quantity, "passed_qty": quantity,
        "size_quantities": [{"size": "M", "quantity": quantity}],
    })


def _setup(client, headers, factory):
    po, work, first = _create(client, headers)
    with TestSessionLocal() as db:
        db.get(ProductionBatch, first).planned_quantity = 300
        second = ProductionBatch(production_order_id=po["id"], batch_no="NASTIL-2",
                                 batch_index=2, name="Nastil 2", planned_quantity=300)
        db.add(second)
        db.commit()
        second_id = second.id
    for bid in (first, second_id):
        response = client.post("/api/cutting/records", headers=headers, json={
            "work_order_id": work["cutting"], "production_batch_id": bid,
            "input_quantity": 10, "input_unit": "kg", "cut_pieces": 300,
            "passed_pieces": 300, "defective_pieces": 0, "waste_quantity": 0,
            "waste_unit": "kg",
            "bundles": [{"color": "white", "size": "M", "quantity": 300, "count": 1}],
        })
        assert response.status_code == 201, response.text
    _issue_required_accessories(client, headers, po["id"])
    with TestSessionLocal() as db:
        # An old accepted shortage must not count again after the next nastil arrives.
        db.get(WorkOrder, work["cutting"]).failed_qty = 300
        for bundle in db.query(Bundle).filter_by(production_order_id=po["id"]):
            bundle.sewing_factory_code = factory
        for operation, code in (
            ("sewing", {"MIL": "SEW", "BST": "BST", "ECO": "ECO"}[factory]),
            ("packaging", {"MIL": "PKG", "BST": "BPK", "ECO": "ECP"}[factory]),
        ):
            db.get(WorkOrder, work[operation]).department_id = db.query(
                Department.id).filter_by(code=code).scalar()
        db.commit()
    scoped_headers = {"Authorization": f"Bearer {create_access_token(1, extra={'factory_code': factory})}"}
    return work, first, second_id, scoped_headers


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_two_sewing_nastils_remain_accessible_and_feed_packaging(client, auth_headers, factory):
    work, first, second, headers = _setup(client, auth_headers, factory)
    wid = work["sewing"]
    if factory != "MIL":
        assert _sew(client, auth_headers, wid, first, 1).status_code == 403
        assert client.post(f"/api/work-orders/{wid}/complete", headers=auth_headers).status_code == 403
    response = _sew(client, headers, wid, first, 300)
    assert response.status_code == 201, response.text
    assert client.get(f"/api/work-orders/{wid}", headers=headers).json()["status"] == "in_progress"
    refused = client.post(f"/api/work-orders/{wid}/complete", headers=headers)
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "Sewing still has unfinished quantities. Continue sewing the remaining nastils."
    progress = client.get(f"/api/work-orders/{wid}/sewing-batch-progress", headers=headers).json()
    assert next(row for row in progress["items"] if row["id"] == first)["remaining_quantity"] == 0
    assert next(row for row in progress["items"] if row["id"] == second)["remaining_quantity"] == 300
    assert _sew(client, headers, wid, first, 1).status_code == 400
    assert _pack(client, headers, work["packaging"], first, 300).status_code == 201
    assert _pack(client, headers, work["packaging"], second, 1).status_code == 400
    assert _sew(client, headers, wid, second, 280).status_code == 201
    assert client.get(f"/api/work-orders/{wid}", headers=headers).json()["status"] == "in_progress"
    assert _sew(client, headers, wid, second, 20).status_code == 201
    assert client.get(f"/api/work-orders/{wid}", headers=headers).json()["status"] == "completed"
    assert client.post(f"/api/work-orders/{wid}/complete", headers=headers).status_code == 200
    assert _pack(client, headers, work["packaging"], second, 300).status_code == 201
    assert client.get(f"/api/work-orders/{work['packaging']}", headers=headers).json()["status"] == "completed"


def test_historically_completed_sewing_reopens_when_remaining_nastil_is_recorded(client, auth_headers):
    work, first, second, headers = _setup(client, auth_headers, "MIL")
    wid = work["sewing"]
    assert _sew(client, headers, wid, first, 300).status_code == 201
    with TestSessionLocal() as db:
        wo = db.get(WorkOrder, wid)
        wo.status, wo.end_time = "completed", datetime.now(timezone.utc)
        db.commit()
    assert _sew(client, headers, wid, second, 100).status_code == 201
    detail = client.get(f"/api/work-orders/{wid}", headers=headers).json()
    assert detail["status"] == "in_progress"
    assert detail["end_time"] is None
    assert detail["passed_qty"] == 400


def test_finishing_first_line_assignment_keeps_second_nastil_available(client, auth_headers):
    work, first, second, headers = _setup(client, auth_headers, "MIL")
    wid = work["sewing"]
    with TestSessionLocal() as db:
        flow = SewingFlow(factory_code="MIL", name="Nastil test line", code="NASTIL-TEST")
        db.add(flow)
        db.flush()
        assignments = [SewingAssignment(work_order_id=wid, production_batch_id=bid,
                                       sewing_flow_id=flow.id, quantity=300)
                       for bid in (first, second)]
        db.add_all(assignments)
        db.commit()
        first_assignment, second_assignment = [row.id for row in assignments]
    assert _sew(client, headers, wid, first, 300, first_assignment).status_code == 201
    rows = client.get(f"/api/work-orders/{wid}/assignments", headers=headers).json()
    assert next(row for row in rows if row["id"] == first_assignment)["status"] == "completed"
    assert next(row for row in rows if row["id"] == second_assignment)["status"] == "planned"
    assert client.get(f"/api/work-orders/{wid}", headers=headers).json()["status"] == "in_progress"
    assert _sew(client, headers, wid, second, 300, second_assignment).status_code == 201
    assert client.get(f"/api/work-orders/{wid}", headers=headers).json()["status"] == "completed"


@pytest.mark.parametrize("cut_passed,cut_failed,sew_passed,sew_failed", [
    (300, 300, 300, 0),  # genuinely accepted Cutting shortfall
    (590, 10, 585, 5),  # real Cutting and Sewing defects
])
def test_sewing_can_complete_with_genuine_losses(client, auth_headers, cut_passed, cut_failed, sew_passed, sew_failed):
    _, work, _ = _create(client, auth_headers, batched=False)
    with TestSessionLocal() as db:
        cut = db.get(WorkOrder, work["cutting"])
        cut.passed_qty, cut.failed_qty = cut_passed, cut_failed
        sew = db.get(WorkOrder, work["sewing"])
        sew.passed_qty, sew.failed_qty = sew_passed, sew_failed
        db.commit()
    response = client.post(f"/api/work-orders/{work['sewing']}/complete", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
