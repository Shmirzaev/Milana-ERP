"""Characterize batch roll-weight replacement at its HTTP and audit boundary."""

import pytest

from app.db import session as session_module
from app.models.inventory import stock_service
from app.schemas import AuditLog, Item, StockBatch, Warehouse
from app.tests.test_eco_transfers import fabric_batch, send  # noqa: F401
from app.tests.test_inventory_access_restore import scoped_headers  # noqa: F401


def make_batch(*, category="fabric", unit="kg", lengths=None):
    with session_module.SessionLocal() as db:
        item = db.query(Item).filter_by(category=category).first()
        warehouse = db.query(Warehouse).first()
        batch = StockBatch(
            item_id=item.id,
            warehouse_id=warehouse.id,
            batch_no="ROLL-WEIGHT-CHARACTERIZATION",
            quantity=30,
            unit=unit,
            qc_status="hold",
            piece_count=2,
            roll_weights_kg=[10, 20],
            roll_lengths_m=lengths or [],
        )
        db.add(batch)
        db.commit()
        return batch.id


def snapshot(batch_id):
    with session_module.SessionLocal() as db:
        batch = db.get(StockBatch, batch_id)
        audits = db.query(AuditLog).filter_by(
            entity_type="StockBatch", entity_id=batch_id, action="save_roll_weights"
        ).order_by(AuditLog.id).all()
        return (
            float(batch.quantity), batch.piece_count, list(batch.roll_weights_kg),
            list(batch.roll_lengths_m),
            [(row.old_value_json, row.new_value_json) for row in audits],
        )


def test_repeated_save_preserves_response_and_records_each_audit(client, auth_headers):
    batch_id = make_batch(lengths=[10, None])
    path = f"/api/inventory/batches/{batch_id}/roll-weights"
    payload = {"roll_weights_kg": [12.25001, 17.74999]}
    for _ in range(2):
        response = client.put(path, json=payload, headers=auth_headers)
        assert response.status_code == 200, response.text
        result = response.json()
        assert (result["quantity"], result["piece_count"], result["roll_weights_kg"],
                result["roll_lengths_m"]) == (30, 2, [12.25, 17.75], [10, None])
    state = snapshot(batch_id)
    assert state[:4] == (30, 2, [12.25, 17.75], [10, None])
    assert state[4] == [
        ({"piece_count": 2, "roll_weights_kg": [10.0, 20.0]},
         {"piece_count": 2, "roll_weights_kg": [12.25, 17.75]}),
        ({"piece_count": 2, "roll_weights_kg": [12.25, 17.75]},
         {"piece_count": 2, "roll_weights_kg": [12.25, 17.75]}),
    ]


@pytest.mark.parametrize(
    "payload,status,detail",
    [
        ({}, 422, None),
        ({"roll_weights_kg": []}, 422, None),
        ({"roll_weights_kg": [1] * 1001}, 422, None),
        ({"roll_weights_kg": [0, 30]}, 400, "Roll 1 weight must be greater than zero"),
        ({"roll_weights_kg": [-1, 31]}, 400, "Roll 1 weight must be greater than zero"),
        ({"roll_weights_kg": [10, 15]}, 409, "Roll weights total 25 kg does not match batch quantity 30 kg"),
        ({"roll_weights_kg": [30]}, 409, "Cannot change roll count after individual roll lengths have been recorded"),
    ],
)
def test_refusals_leave_batch_and_audit_untouched(client, auth_headers, payload, status, detail):
    batch_id = make_batch(lengths=[10, None])
    before = snapshot(batch_id)
    response = client.put(f"/api/inventory/batches/{batch_id}/roll-weights", json=payload, headers=auth_headers)
    assert response.status_code == status, response.text
    if detail is not None:
        assert response.json()["detail"] == detail
    assert snapshot(batch_id) == before


@pytest.mark.parametrize(
    "category,unit,detail",
    [
        ("accessory", "kg", "Roll weights are only supported for materials"),
        ("fabric", "m", "Material roll weights require kilogram units"),
    ],
)
def test_category_and_unit_refusals(client, auth_headers, category, unit, detail):
    batch_id = make_batch(category=category, unit=unit)
    before = snapshot(batch_id)
    response = client.put(f"/api/inventory/batches/{batch_id}/roll-weights",
                          json={"roll_weights_kg": [30]}, headers=auth_headers)
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == detail
    assert snapshot(batch_id) == before


def test_audit_failure_rolls_back_batch_and_audit(client, auth_headers, monkeypatch):
    batch_id = make_batch()
    before = snapshot(batch_id)
    original = stock_service.log_action

    def fail_after_audit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected roll-weight audit failure")

    monkeypatch.setattr(stock_service, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="injected roll-weight audit failure"):
        client.put(f"/api/inventory/batches/{batch_id}/roll-weights",
                   json={"roll_weights_kg": [12, 18]}, headers=auth_headers)
    assert snapshot(batch_id) == before


def test_material_only_actor_cannot_save_accessory_batch(client, scoped_headers):
    batch_id = make_batch(category="accessory")
    before = snapshot(batch_id)
    response = client.put(f"/api/inventory/batches/{batch_id}/roll-weights",
                          json={"roll_weights_kg": [12, 18]}, headers=scoped_headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Only material inventory is available to this user"
    assert snapshot(batch_id) == before


def test_outstanding_custody_refuses_save_without_batch_or_audit_changes(client, auth_headers, fabric_batch):
    result = send(client, auth_headers, fabric_batch)
    assert result.status_code == 200, result.text
    before = snapshot(fabric_batch)
    response = client.put(f"/api/inventory/batches/{fabric_batch}/roll-weights",
                          json={"roll_weights_kg": [35]}, headers=auth_headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Return outstanding fabric through the Eco Cotton register before changing this batch"
    assert snapshot(fabric_batch) == before
