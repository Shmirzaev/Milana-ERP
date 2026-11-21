"""Characterize Eco send transaction boundaries and retry behavior."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.inventory import transfers_service
from app.schemas import AuditLog, EcoFabricDispatch, EcoFabricRoll, StockBatch, StockMovement
from app.tests.conftest import TestSessionLocal
from app.tests.test_fabric_scans import fabric_batch  # noqa: F401


def test_send_fallback_weights_flush_lines_and_replay(client, auth_headers, fabric_batch):
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        batch.quantity = Decimal("30.02")
        batch.roll_weights_kg = []
        db.commit()

    phases = []

    def capture_flush(session, _context):
        relevant = [obj for obj in session.new if isinstance(obj, (EcoFabricDispatch, EcoFabricRoll, StockMovement))]
        if relevant:
            phases.append(sorted(type(obj).__name__ for obj in relevant))

    payload = {"request_key": str(uuid4()), "codes": [f"B{fabric_batch}-R2", f"B{fabric_batch}-R1"]}
    event.listen(Session, "after_flush", capture_flush)
    try:
        response = client.post("/api/eco-fabric-transfers/send", headers=auth_headers, json=payload)
    finally:
        event.remove(Session, "after_flush", capture_flush)

    assert response.status_code == 200, response.text
    result = response.json()
    assert [row["code"] for row in result["rows"]] == [f"B{fabric_batch}-R1", f"B{fabric_batch}-R2"]
    assert [Decimal(str(row["quantity"])) for row in result["rows"]] == [Decimal("10.01"), Decimal("10.01")]
    assert phases == [["EcoFabricDispatch"], ["EcoFabricRoll", "StockMovement"], ["EcoFabricRoll", "StockMovement"]]
    replay = client.post("/api/eco-fabric-transfers/send", headers=auth_headers, json=payload)
    assert replay.status_code == 200 and replay.json() == result
    changed = {**payload, "codes": [f"B{fabric_batch}-R3"]}
    refusal = client.post("/api/eco-fabric-transfers/send", headers=auth_headers, json=changed)
    assert refusal.status_code == 409 and refusal.json()["detail"] == "ecoTransfers.changedRequest"
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        assert batch.quantity == Decimal("10.00")
        assert batch.roll_weights_kg == [10.01, 10.01, 10.0]
        assert db.query(EcoFabricDispatch).count() == 1
        assert db.query(EcoFabricRoll).count() == 2
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch", reference_id=result["id"]).count() == 2
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", entity_id=result["id"], action="send").count() == 1


def test_send_audit_failure_rolls_back_and_same_key_can_retry(client, auth_headers, fabric_batch, monkeypatch):
    payload = {"request_key": str(uuid4()), "codes": [f"B{fabric_batch}-R1", f"B{fabric_batch}-R2"]}
    actual_log = transfers_service.log_action

    def fail_after_audit(*args, **kwargs):
        actual_log(*args, **kwargs)
        raise RuntimeError("injected send audit failure")

    monkeypatch.setattr(transfers_service, "log_action", fail_after_audit)
    with pytest.raises(RuntimeError, match="injected send audit failure"):
        client.post("/api/eco-fabric-transfers/send", headers=auth_headers, json=payload)
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        assert batch.quantity == Decimal("45") and batch.archived_at is None
        assert batch.roll_weights_kg == [10, 15, 20]
        assert db.query(EcoFabricDispatch).count() == 0
        assert db.query(EcoFabricRoll).count() == 0
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch").count() == 0
        assert db.query(AuditLog).filter_by(entity_type="EcoFabricDispatch", action="send").count() == 0
    monkeypatch.setattr(transfers_service, "log_action", actual_log)
    response = client.post("/api/eco-fabric-transfers/send", headers=auth_headers, json=payload)
    assert response.status_code == 200, response.text
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == Decimal("20")
        assert db.query(EcoFabricDispatch).count() == 1
        assert db.query(EcoFabricRoll).count() == 2
