"""Transfer transaction and saved replay characterization."""
import pytest
import inspect
from sqlalchemy import event

from app.db.session import SessionLocal
from app.models import idempotency_service
from app.models.inventory import transfers_service
from app.schemas import AuditLog, IdempotencyRecord, StockBatch, StockMovement
from app.tests.test_stock_movement_batch_integrity import _seeded_batch


def test_batch_mutations_originate_in_schema_and_observer_catches_direct_write(client, auth_headers, monkeypatch):
    item, batch, warehouse = _seeded_batch(client, auth_headers, quantity=5)
    origins = []

    def observe(target, value, oldvalue, initiator):
        frames = inspect.stack()
        try:
            origin = next(frame.filename.replace("\\", "/") for frame in frames[1:]
                          if "/app/" in frame.filename.replace("\\", "/")
                          and not frame.filename.replace("\\", "/").endswith("test_transfer_schema_boundary.py"))
            origins.append(origin)
        finally:
            del frames

    fields = (StockBatch.quantity, StockBatch.archived_at, StockBatch.archived_by, StockBatch.warehouse_id)
    for field in fields:
        event.listen(field, "set", observe)
    try:
        response = client.post("/api/inventory/transfer", headers=auth_headers, json={
            "movement_type": "issue", "item_id": item, "batch_id": batch,
            "from_warehouse_id": warehouse, "quantity": 5, "unit": "kg",
        })
        assert response.status_code == 201, response.text
        assert len(origins) >= 4
        assert all(path.endswith("/schemas/inventory/stock_movement_persistence.py") for path in origins)
        # A direct mutation substituted at the same call site must be detected.
        item2, batch2, warehouse2 = _seeded_batch(client, auth_headers, quantity=5)
        origins.clear()

        def direct_write(db, row, quantity):
            row.quantity = quantity

        monkeypatch.setattr(transfers_service.stock_movement_persistence, "set_batch_quantity", direct_write)
        response = client.post("/api/inventory/transfer", headers=auth_headers, json={
            "movement_type": "issue", "item_id": item2, "batch_id": batch2,
            "from_warehouse_id": warehouse2, "quantity": 1, "unit": "kg",
        })
        assert response.status_code == 201, response.text
        assert any(path.endswith("/models/inventory/transfers_service.py") for path in origins)
    finally:
        for field in fields:
            event.remove(field, "set", observe)


def test_saved_fingerprint_and_replay_match_fresh_http_response(client, auth_headers):
    item, batch, warehouse = _seeded_batch(client, auth_headers, quantity=5)
    body = {"movement_type": "issue", "item_id": item, "batch_id": batch,
            "from_warehouse_id": warehouse, "quantity": 5, "unit": "kg"}
    headers = {**auth_headers, "Idempotency-Key": "transfer-boundary-test"}
    first = client.post("/api/inventory/transfer", headers=headers, json=body)
    assert first.status_code == 201, first.text
    with SessionLocal() as db:
        saved = db.query(IdempotencyRecord).filter_by(key="transfer-boundary-test").one()
        # This is the historical service fingerprint boundary, before the typed result.
        expected = idempotency_service.request_fingerprint({
            "movement_type": "issue", "item_id": item, "batch_id": batch,
            "from_warehouse_id": warehouse, "to_warehouse_id": None,
            "quantity": 5.0, "unit": "kg", "reference_type": None, "reference_id": None,
        })
        assert saved.request_hash == expected
        assert saved.response_json == first.json()
    replay = client.post("/api/inventory/transfer", headers=headers, json=body)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    with SessionLocal() as db:
        row = db.get(StockBatch, batch)
        assert row.quantity == 0 and row.archived_at is not None
        assert db.query(StockMovement).filter_by(batch_id=batch, movement_type="issue").count() == 1
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch, action="archive_depleted").count() == 1


@pytest.mark.parametrize("fault_point", ["movement_audit", "after_idempotency"])
def test_failure_after_depletion_rolls_back_then_retry_succeeds(client, auth_headers, monkeypatch, fault_point):
    item, batch, warehouse = _seeded_batch(client, auth_headers, quantity=5)
    body = {"movement_type": "issue", "item_id": item, "batch_id": batch,
            "from_warehouse_id": warehouse, "quantity": 5, "unit": "kg"}
    headers = {**auth_headers, "Idempotency-Key": "transfer-fault-test"}
    original_audit = transfers_service.log_action
    original_store = transfers_service.store_idempotent_response

    def fail(*args, **kwargs):
        raise RuntimeError("injected transfer failure")

    def store_then_fail(*args, **kwargs):
        original_store(*args, **kwargs)
        fail()

    if fault_point == "movement_audit":
        monkeypatch.setattr(transfers_service, "log_action", fail)
    else:
        monkeypatch.setattr(transfers_service, "store_idempotent_response", store_then_fail)
    with pytest.raises(RuntimeError, match="injected transfer failure"):
        client.post("/api/inventory/transfer", headers=headers, json=body)
    with SessionLocal() as db:
        row = db.get(StockBatch, batch)
        assert row.quantity == 5 and row.archived_at is None and row.archived_by is None
        assert db.query(StockMovement).filter_by(batch_id=batch, movement_type="issue").count() == 0
        assert db.query(AuditLog).filter_by(entity_type="StockBatch", entity_id=batch, action="archive_depleted").count() == 0
        assert db.query(IdempotencyRecord).filter_by(key="transfer-fault-test").count() == 0
    monkeypatch.setattr(transfers_service, "log_action", original_audit)
    monkeypatch.setattr(transfers_service, "store_idempotent_response", original_store)
    response = client.post("/api/inventory/transfer", headers=headers, json=body)
    assert response.status_code == 201, response.text
