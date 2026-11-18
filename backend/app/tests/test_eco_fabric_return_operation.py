"""Eco return parity and participant failure checks."""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.libs.enums.inventory import StockMovementType
from app.models.inventory import transfers_service
from app.schemas import EcoFabricDispatch, EcoFabricRoll, StockBatch, StockMovement
from app.tests.conftest import TestSessionLocal
from app.tests.test_eco_transfers import send
from app.tests.test_fabric_scans import fabric_batch  # noqa: F401


def test_return_persists_custody_stock_and_ledger_once(client, auth_headers, fabric_batch):
    dispatch = send(client, auth_headers, fabric_batch, (1, 2, 3)).json()
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        assert batch.quantity == 0 and batch.archived_at is not None
        snapshot = db.get(EcoFabricDispatch, dispatch["id"]).remaining_inventory
    payload = {"code": f"B{fabric_batch}-R2", "dispatch_id": dispatch["id"], "request_key": str(uuid4())}
    first = client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload)
    assert first.status_code == 200
    assert client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload).json() == first.json()
    changed = {**payload, "code": f"B{fabric_batch}-R1"}
    assert client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=changed).status_code == 409
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        row = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch["id"], roll_number=2).one()
        movement = db.query(StockMovement).filter_by(reference_type="EcoFabricReturn").one()
        assert batch.quantity == Decimal("15") and batch.archived_at is None and batch.archived_by is None
        assert batch.roll_weights_kg == [10, 15, 20] and batch.piece_count == 3
        assert row.return_key == payload["request_key"] and row.returned_at and row.returned_by
        assert row.return_operator_name == first.json()["return_operator_name"]
        assert (movement.movement_type, movement.batch_id, movement.reference_id, movement.quantity) == (
            StockMovementType.RETURN.value, batch.id, row.id, row.quantity,
        )
        assert db.get(EcoFabricDispatch, dispatch["id"]).remaining_inventory == snapshot


def test_audit_failure_rolls_back_return_and_allows_retry(client, auth_headers, fabric_batch, monkeypatch):
    dispatch = send(client, auth_headers, fabric_batch, (2,)).json()
    payload = {"code": f"B{fabric_batch}-R2", "dispatch_id": dispatch["id"], "request_key": str(uuid4())}
    actual_log = transfers_service.log_action

    def fail_after_audit(*args, **kwargs):
        actual_log(*args, **kwargs)
        raise RuntimeError("injected audit participant failure")

    monkeypatch.setattr(transfers_service, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="injected audit"):
        client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload)
    with TestSessionLocal() as db:
        row = db.query(EcoFabricRoll).filter_by(dispatch_id=dispatch["id"]).one()
        assert row.returned_at is None and row.return_key is None
        assert db.get(StockBatch, fabric_batch).quantity == Decimal("30")
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricReturn").count() == 0
    monkeypatch.setattr(transfers_service, "log_action", actual_log)
    assert client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload).status_code == 200
