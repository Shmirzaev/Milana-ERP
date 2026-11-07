"""Manual receipt line choice reuses atomic Nastil acceptance, without duplicate work."""
from uuid import uuid4

import pytest

from app.schemas import Bundle, BundleScanLog, SewingAssignment, SewingFlow, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_packaging_sewing_output import _create
from app.tests.test_sewing_later_nastil_workflow import cut
from app.tests.test_production_flow import _issue_required_accessories


@pytest.fixture
def waiting(client, auth_headers):
    order, work, batch_id = _create(client, auth_headers)
    cut(client, auth_headers, work, batch_id)
    _issue_required_accessories(client, auth_headers, order["id"])
    with TestSessionLocal() as db:
        flow = SewingFlow(factory_code="MIL", code="MANUAL-" + uuid4().hex[:8], name="Manual line")
        db.add(flow)
        db.commit()
        flow_id = flow.id
        bundle_ids = [row.id for row in db.query(Bundle).filter_by(production_batch_id=batch_id).all()]
    return order, work, batch_id, flow_id, bundle_ids


def receive(client, headers, waiting, **changes):
    order, _, batch_id, flow_id, _ = waiting
    return client.post("/api/bundles/manual-receive-sewing", headers=headers, json={
        "production_order_id": order["id"], "production_batch_id": batch_id, "model_id": 1,
        "factory_code": "MIL", "sewing_flow_id": flow_id, **changes,
    })


def test_manual_receipt_can_assign_and_retry_without_duplicate_work(client, auth_headers, waiting):
    order, work, batch_id, flow_id, ids = waiting
    response = receive(client, auth_headers, waiting)
    assert response.status_code == 200, response.text
    assert response.json()["received_quantity"] == 128
    assert set(response.json()["bundle_ids"]) == set(ids)
    assignment_id = response.json()["sewing_assignment_id"]
    retry = receive(client, auth_headers, waiting)
    assert retry.status_code == 200, retry.text
    assert retry.json()["received_count"] == 0
    assert retry.json()["sewing_assignment_id"] == assignment_id
    with TestSessionLocal() as db:
        assignment = db.get(SewingAssignment, assignment_id)
        assert (assignment.production_batch_id, assignment.sewing_flow_id, assignment.quantity, assignment.status) == (batch_id, flow_id, 128, "in_progress")
        assert db.get(WorkOrder, work["sewing"]).sewing_flow_id == flow_id
        assert db.query(SewingAssignment).filter_by(work_order_id=work["sewing"]).count() == 1
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(ids), BundleScanLog.scan_type == "received_sewing").count() == 4
        assert all(db.get(Bundle, bid).status == "received_sewing" for bid in ids)
    context = client.get(f"/api/sewing-daily-reports/line-context?sewing_flow_id={flow_id}", headers=auth_headers)
    assert context.status_code == 200, context.text
    assert any(row["sewing_assignment_id"] == assignment_id for row in context.json()["active_work_orders"])


@pytest.mark.parametrize("planned", [False, True])
def test_manual_receipt_without_line_preserves_existing_plan(client, auth_headers, waiting, planned):
    _, work, batch_id, flow_id, ids = waiting
    if planned:
        with TestSessionLocal() as db:
            db.add(SewingAssignment(work_order_id=work["sewing"], production_batch_id=batch_id, sewing_flow_id=flow_id, quantity=128, status="planned"))
            db.get(WorkOrder, work["sewing"]).sewing_flow_id = flow_id
            db.commit()
    result = receive(client, auth_headers, waiting, sewing_flow_id=None)
    assert result.status_code == 200, result.text
    with TestSessionLocal() as db:
        assignments = db.query(SewingAssignment).filter_by(work_order_id=work["sewing"]).all()
        assert len(assignments) == int(planned)
        if planned:
            assert (assignments[0].sewing_flow_id, assignments[0].quantity, assignments[0].status) == (flow_id, 128, "planned")
        assert db.get(WorkOrder, work["sewing"]).sewing_flow_id == (flow_id if planned else None)
        assert all(db.get(Bundle, bid).status == "received_sewing" for bid in ids)


@pytest.mark.parametrize("refusal", ["inactive", "factory", "missing", "assigned", "order", "model"])
def test_manual_line_refusal_is_atomic(client, auth_headers, waiting, refusal):
    _, work, batch_id, flow_id, ids = waiting
    changes = {}
    with TestSessionLocal() as db:
        flow = db.get(SewingFlow, flow_id)
        if refusal == "inactive":
            flow.is_active = False
        elif refusal == "factory":
            flow.factory_code = "ECO"
        elif refusal == "missing":
            changes["sewing_flow_id"] = 999999
        elif refusal == "assigned":
            other = db.query(SewingFlow).filter_by(code="SEW-01").one()
            db.add(SewingAssignment(work_order_id=work["sewing"], production_batch_id=batch_id, sewing_flow_id=other.id, quantity=128, status="planned"))
        elif refusal == "order":
            changes["production_order_id"] = 999999
        elif refusal == "model":
            changes["model_id"] = 999999
        db.commit()
    response = receive(client, auth_headers, waiting, **changes)
    assert response.status_code in (400, 403, 404, 409), response.text
    with TestSessionLocal() as db:
        assert all(db.get(Bundle, bid).status == "created" for bid in ids)
        assert db.query(BundleScanLog).filter(BundleScanLog.bundle_id.in_(ids), BundleScanLog.scan_type == "received_sewing").count() == 0
        assert db.query(SewingAssignment).filter_by(sewing_flow_id=flow_id).count() == 0
        assert db.get(WorkOrder, work["sewing"]).sewing_flow_id is None


def test_manual_line_choice_requires_a_batch(client, auth_headers, waiting):
    response = receive(client, auth_headers, waiting, production_batch_id=None)
    assert response.status_code == 400
    assert "Nastil" in response.json()["detail"]


def test_manual_receipt_dto_uses_canonical_factory_enum():
    from app.libs.dto.production.sewing_manual_receive import SewingManualReceiveIn
    from app.libs.enums.production import SewingFactoryCode
    from pydantic import ValidationError

    payload = SewingManualReceiveIn(production_order_id=1, production_batch_id=None, factory_code=" bst ")
    assert payload.factory_code is SewingFactoryCode.BESTTEX
    assert SewingManualReceiveIn(production_order_id=1, production_batch_id=None).factory_code is None
    for invalid in ("ECT", 0, False, []):
        with pytest.raises(ValidationError):
            SewingManualReceiveIn(production_order_id=1, production_batch_id=None, factory_code=invalid)


def test_manual_line_receipt_does_not_bypass_accessory_gate(client, auth_headers):
    order, work, batch_id = _create(client, auth_headers)
    cut(client, auth_headers, work, batch_id)
    flow = next(row for row in client.get("/api/sewing-flows", headers=auth_headers).json() if row["code"] == "SEW-01")
    response = client.post("/api/bundles/manual-receive-sewing", headers=auth_headers, json={
        "production_order_id": order["id"], "production_batch_id": batch_id, "sewing_flow_id": flow["id"],
    })
    assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert db.query(SewingAssignment).filter_by(work_order_id=work["sewing"]).count() == 0
        assert all(row.status == "created" for row in db.query(Bundle).filter_by(production_batch_id=batch_id))


def test_browser_fixture_builds_waiting_batch_and_saved_parts(client, auth_headers):
    from app.tests.sewing_receipt_browser_fixture import seed_sewing_receipt_browser

    client.headers.update(auth_headers)
    fixture = seed_sewing_receipt_browser(client, report_date="2099-11-07")
    options = client.get("/api/bundles/sewing-receive-options?factory_code=MIL").json()
    row = next(row for row in options if row["production_batch_id"] == fixture["batch_id"])
    assert row["quantity"] == 128 and row["bundle_count"] == 4
    rows = client.get("/api/sewing-daily-reports?report_date=2099-11-07").json()["rows"]
    saved = [row for row in rows if row["id"] in fixture["report_ids"]]
    assert sorted((row["top_qty"], row["bottom_qty"]) for row in saved) == [(0, 16), (24, 0)]
