from datetime import datetime, timezone
from uuid import uuid4
import pytest
from sqlalchemy import event
from app.models import (StockBatch, StockMovement, EcoFabricDispatch, EcoFabricRoll, User, Role, Item,
                        MaterialReservation, ProductionOrder)
from app.tests.conftest import TestSessionLocal, test_engine
from app.core.deps import get_current_user
from app.main import app
from app.tests.test_fabric_scans import fabric_batch  # noqa: F401


def send(client, headers, batch, rolls=(1,), key=None):
    return client.post("/api/eco-fabric-transfers/send", headers=headers,
        json={"codes": [f"B{batch}-R{roll}" for roll in rolls], "request_key": key or str(uuid4())})


def test_dispatch_return_inventory_and_immutable_pdf(client, auth_headers, fabric_batch):
    key = str(uuid4())
    result = send(client, auth_headers, fabric_batch, (1, 2, 3), key)
    assert result.status_code == 200, result.text
    dispatch = result.json()
    assert dispatch["sent_rolls"] == 3 and float(dispatch["sent_kg"]) == 45
    assert send(client, auth_headers, fabric_batch, (1, 2, 3), key).json()["id"] == dispatch["id"]
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        assert batch.quantity == 0 and batch.archived_at
        assert batch.roll_weights_kg == [10, 15, 20] and batch.piece_count == 3
        saved = db.get(EcoFabricDispatch, dispatch["id"]).remaining_inventory
        assert not any(row["batch_no"] == "DAILY-ROLLS" for row in saved)
        assert db.query(EcoFabricDispatch).count() == 1
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricDispatch").count() == 3
    assert send(client, auth_headers, fabric_batch).status_code == 409
    scan = client.post("/api/eco-fabric-transfers/scan", headers=auth_headers, json={"code": f"B{fabric_batch}-R2"})
    assert scan.json()["status"] == "sent"
    payload = {"code": f"B{fabric_batch}-R2", "dispatch_id": dispatch["id"], "request_key": str(uuid4())}
    for _ in range(2):
        returned = client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload)
        assert returned.status_code == 200, returned.text
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        assert batch.quantity == 15 and batch.archived_at is None
        assert db.query(StockMovement).filter_by(reference_type="EcoFabricReturn").count() == 1
        assert db.get(EcoFabricDispatch, dispatch["id"]).remaining_inventory == saved
    report = client.get("/api/eco-fabric-transfers", headers=auth_headers).json()
    assert report["outstanding_rolls"] == 2 and float(report["outstanding_kg"]) == 30
    # Return then resend is a new custody cycle. A delayed old retry cannot restore it.
    second = send(client, auth_headers, fabric_batch, (2,)).json()
    assert second["id"] != dispatch["id"]
    assert client.post("/api/eco-fabric-transfers/return", headers=auth_headers, json=payload).status_code == 200
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == 0
    for lang in ["en", "ru", "uz"]:
        pdf = client.get(f'/api/eco-fabric-transfers/{dispatch["id"]}/pdf?lang={lang}', headers=auth_headers)
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_dispatch_inventory_snapshot_projects_only_payload_columns(client, auth_headers, fabric_batch):
    legacy_inventory_sql = ""
    statements = []
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        fabric_name = db.get(Item, batch.item_id).name
        legacy_inventory_sql = str(
            db.query(StockBatch, Item)
            .join(Item, Item.id == StockBatch.item_id)
            .statement.compile(dialect=db.bind.dialect)
        ).lower()

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select"):
            statements.append(" ".join(statement.lower().split()))

    event.listen(test_engine, "before_cursor_execute", capture)
    try:
        response = send(client, auth_headers, fabric_batch, (1,))
    finally:
        event.remove(test_engine, "before_cursor_execute", capture)

    assert response.status_code == 200, response.text
    assert "remaining_inventory" not in response.json()
    with TestSessionLocal() as db:
        snapshot = next(
            row for row in db.query(EcoFabricDispatch).one().remaining_inventory
            if row["batch_no"] == "DAILY-ROLLS"
        )
    assert snapshot == {
        "fabric_name": fabric_name,
        "batch_no": "DAILY-ROLLS",
        "color": "Blue",
        "quantity": "35.0000",
        "unit": "kg",
        "rolls": 2,
    }
    inventory_reads = [
        statement for statement in statements
        if " from stock_batches " in statement and " join items " in statement
    ]
    assert len(inventory_reads) == 1
    assert "stock_batches.id" in inventory_reads[0]
    assert "items.name" in inventory_reads[0]
    assert "roll_weights_kg" not in inventory_reads[0]
    assert "items.composition_json" not in inventory_reads[0]
    assert "stock_batches.roll_weights_kg" in legacy_inventory_sql
    assert "items.composition_json" in legacy_inventory_sql


@pytest.mark.parametrize("rolls", [(1, 1), (1, 99)])
def test_dispatch_validation_is_atomic(client, auth_headers, fabric_batch, rolls):
    assert send(client, auth_headers, fabric_batch, rolls).status_code in (400, 409)
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == 45
        assert db.query(EcoFabricDispatch).count() == 0
        assert db.query(EcoFabricRoll).count() == 0


def test_scan_is_read_only_and_return_requires_dispatch(client, auth_headers, fabric_batch):
    response = client.post("/api/eco-fabric-transfers/scan", headers=auth_headers, json={"code": f"B{fabric_batch}-R1"})
    assert response.status_code == 200 and float(response.json()["quantity"]) == 10
    assert client.post("/api/eco-fabric-transfers/return", headers=auth_headers,
        json={"code": f"B{fabric_batch}-R1", "dispatch_id": 999, "request_key": str(uuid4())}).status_code == 409
    oversized = client.post("/api/eco-fabric-transfers/return", headers=auth_headers,
        json={"code": f"B{fabric_batch}-R1", "dispatch_id": 2_147_483_648, "request_key": str(uuid4())})
    assert oversized.status_code == 409
    assert oversized.json()["detail"] == "ecoTransfers.notSent"
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == 45
        assert db.query(EcoFabricDispatch).count() == 0


def test_outstanding_rolls_block_batch_identity_edits_and_manual_restore(client, auth_headers, fabric_batch):
    result = send(client, auth_headers, fabric_batch)
    assert result.status_code == 200
    for method, path, payload in [("patch", f"/api/inventory/batches/{fabric_batch}", {"quantity": 99}),
                                 ("put", f"/api/inventory/batches/{fabric_batch}/roll-weights", {"roll_weights_kg": [35]}),
                                 ("delete", f"/api/inventory/batches/{fabric_batch}", None)]:
        response = client.request(method, path, headers=auth_headers, json=payload)
        assert response.status_code == 409, response.text
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == 35


@pytest.mark.parametrize("factory,permissions,expected", [("MIL", ["inventory.eco_transfers"], 200),
    ("MIL", ["storage.items"], 403), ("ECO", ["inventory.eco_transfers"], 403), ("BST", ["*"], 403)])
def test_scoped_access(client, fabric_batch, factory, permissions, expected):
    with TestSessionLocal() as db:
        role = Role(name="Eco test", permissions=permissions)
        user = User(name="Test", email="eco-test@example.com", password_hash="unused", role=role, factory_code=factory)
        db.add(user); db.commit()
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            assert client.get("/api/eco-fabric-transfers").status_code == expected
            assert client.post("/api/eco-fabric-transfers/scan", json={"code": f"B{fabric_batch}-R1"}).status_code == expected
        finally:
            app.dependency_overrides.pop(get_current_user)


def test_reserved_stock_cannot_leave(client, auth_headers, fabric_batch):
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        order = ProductionOrder(production_no="PO-ECO-TEST", model_id=1, planned_quantity=50, production_type="branded_stock")
        db.add(order); db.flush()
        db.add(MaterialReservation(reservation_no="RES-ECO", production_order_id=order.id, item_id=batch.item_id,
            stock_batch_id=batch.id, warehouse_id=batch.warehouse_id, reserved_quantity=40, unit="kg", status="reserved"))
        db.commit()
    assert send(client, auth_headers, fabric_batch).status_code == 409
    with TestSessionLocal() as db:
        assert db.get(StockBatch, fabric_batch).quantity == 45


def test_daily_history_uses_tashkent_date(client, auth_headers, fabric_batch):
    result = send(client, auth_headers, fabric_batch).json()
    with TestSessionLocal() as db:
        db.get(EcoFabricDispatch, result["id"]).sent_at = datetime(2026, 9, 17, 20, tzinfo=timezone.utc)
        db.commit()
    assert client.get("/api/eco-fabric-transfers?report_date=2026-09-18", headers=auth_headers).json()["total"] == 1
    assert client.get("/api/eco-fabric-transfers?report_date=2026-09-17", headers=auth_headers).json()["total"] == 0


def test_partial_dispatch_updates_available_rolls_and_keeps_qr_identity(client, auth_headers, fabric_batch):
    assert send(client, auth_headers, fabric_batch, (2,)).status_code == 200
    response = client.get("/api/inventory/batches?group=materials", headers=auth_headers)
    assert response.status_code == 200, response.text
    row = next(row for row in response.json() if row["id"] == fabric_batch)
    assert row["quantity"] == 30 and row["available_piece_count"] == 2
    assert row["piece_count"] == 3 and row["offsite_roll_numbers"] == [2]
    assert row["roll_weights_kg"] == [10, 15, 20]
    with TestSessionLocal() as db:
        snapshot = db.query(EcoFabricDispatch).one().remaining_inventory
        entry = next(row for row in snapshot if row["batch_no"] == "DAILY-ROLLS")
        assert entry["rolls"] == 2 and float(entry["quantity"]) == 30
