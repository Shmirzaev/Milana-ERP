from uuid import uuid4

import pytest

from app.models import Bundle, BundleScanLog, ProductionBatch, WorkOrder
from app.tests.conftest import TestSessionLocal
from app.tests.test_bundle_receiving_factory_scope import _headers, _ready_bundle


def two_batches(factory="BST"):
    first_id, work_id, order_id, _ = _ready_bundle(factory, "created")
    with TestSessionLocal() as db:
        batches = [ProductionBatch(production_order_id=order_id, batch_no=f"TEST-{i}",
                                   batch_index=i, name=f"Batch {i}", planned_quantity=qty)
                   for i, qty in ((1, 450), (2, 510))]
        db.add_all(batches)
        db.flush()
        first = db.get(Bundle, first_id)
        first.production_batch_id = batches[0].id
        first.quantity = 450
        extra = Bundle(bundle_no=f"EXTRA-{uuid4().hex}", barcode=uuid4().hex,
                       production_order_id=order_id, production_batch_id=batches[1].id,
                       model_id=first.model_id, color=first.color, size=first.size, quantity=510,
                       current_department_id=first.current_department_id, next_department_id=first.next_department_id,
                       sewing_factory_code=factory, status="created")
        db.add(extra)
        db.commit()
        return order_id, work_id, first_id, extra.id, batches[0].id, batches[1].id


@pytest.mark.parametrize("factory", ["MIL", "BST", "ECO"])
def test_receive_extra_batch_leaves_first_waiting_then_receive_first(client, auth_headers, factory):
    order_id, work_id, first_id, extra_id, first_batch, extra_batch = two_batches(factory)
    headers = _headers(client, auth_headers, factory, ["sewing.bundles", "sewing.flows"])
    options = client.get("/api/bundles/sewing-receive-options", headers=headers).json()
    rows = [row for row in options if row["production_order_id"] == order_id]
    assert {row["production_batch_id"]: row["quantity"] for row in rows} == {first_batch: 450, extra_batch: 510}
    assert all(row["batch_label"] and row["bundle_count"] == 1 for row in rows)
    payload = {"production_order_id": order_id, "production_batch_id": extra_batch, "model_id": 1}
    received = client.post("/api/bundles/manual-receive-sewing", json=payload, headers=headers)
    assert received.status_code == 200, received.text
    assert received.json()["bundle_ids"] == [extra_id]
    assert received.json()["received_quantity"] == 510
    with TestSessionLocal() as db:
        assert db.get(Bundle, first_id).status == "created"
        assert db.get(Bundle, extra_id).status == "received_sewing"
        assert db.query(BundleScanLog).filter_by(bundle_id=first_id).count() == 0
        assert db.get(WorkOrder, work_id).actual_input_qty == 510
    queue = client.get(f"/api/work-orders?operation=sewing&only_received_sewing=true&sewing_factory_code={factory}", headers=headers)
    assert queue.status_code == 200, queue.text
    assert {row["production_batch_id"] for row in queue.json() if row["production_order_id"] == order_id} == {extra_batch}
    # A duplicate request cannot spill into another still-waiting batch.
    assert client.post("/api/bundles/manual-receive-sewing", json=payload, headers=headers).status_code == 404
    payload["production_batch_id"] = first_batch
    assert client.post("/api/bundles/manual-receive-sewing", json=payload, headers=headers).status_code == 200
    with TestSessionLocal() as db:
        assert db.get(WorkOrder, work_id).actual_input_qty == 960


@pytest.mark.parametrize("batch_selection", ["missing", None, 999999])
def test_omitted_null_or_wrong_batch_cannot_receive_whole_order(client, auth_headers, batch_selection):
    order_id, _, first_id, extra_id, _, _ = two_batches("MIL")
    payload = {"production_order_id": order_id}
    if batch_selection != "missing":
        payload["production_batch_id"] = batch_selection
    response = client.post("/api/bundles/manual-receive-sewing", json=payload, headers=auth_headers)
    assert response.status_code == (422 if batch_selection == "missing" else 404), response.text
    with TestSessionLocal() as db:
        assert db.get(Bundle, first_id).status == db.get(Bundle, extra_id).status == "created"


def test_batch_from_another_order_cannot_receive_either_order(client, auth_headers):
    order_id, _, first_id, _, _, _ = two_batches("MIL")
    _, _, foreign_id, _, foreign_batch, _ = two_batches("MIL")
    response = client.post("/api/bundles/manual-receive-sewing", headers=auth_headers,
                           json={"production_order_id": order_id, "production_batch_id": foreign_batch})
    assert response.status_code == 404
    with TestSessionLocal() as db:
        assert db.get(Bundle, first_id).status == db.get(Bundle, foreign_id).status == "created"
