from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.api.routes import fabric_scans
from app.core.deps import get_current_user
from app.db.base import Base
from app.main import app
from app.models import Item, Role, StockBatch, User, Warehouse
from app.models.fabric_scan import FabricScan
from app.tests.conftest import TestSessionLocal


@pytest.fixture
def fabric_batch():
    with TestSessionLocal() as db:
        item = db.query(Item).filter_by(category="fabric").first()
        warehouse = db.query(Warehouse).first()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="DAILY-ROLLS",
                           quantity=45, piece_count=3, roll_weights_kg=[10, 15, 20],
                           unit="kg", cost_per_unit=2, color="Blue")
        db.add(batch)
        db.commit()
        return batch.id


def scan(client, headers, batch, direction="received", code=None):
    return client.post("/api/fabric-scans", headers=headers,
                       json={"code": code or f"B{batch}-R1", "direction": direction})


def fingerprint():
    # Compare every existing table, including stock, reservations, production and audit.
    with TestSessionLocal() as db:
        return {table.name: sorted(repr(tuple(row)) for row in db.execute(select(table)).all())
                for table in Base.metadata.sorted_tables if table.name != "fabric_scans"}


def test_receipt_return_and_duplicate_touch_only_register(client, auth_headers, fabric_batch):
    before = fingerprint()
    qr = f"https://erp.milanapremium.uz/inventory?group=materials&q=anything&batch_id={fabric_batch}&roll=1&roll_total=999"
    first = scan(client, auth_headers, fabric_batch, code=qr)
    assert first.status_code == 200, first.text
    assert first.json()["duplicate"] is False
    again = scan(client, auth_headers, fabric_batch)
    assert again.json()["duplicate"] is True
    assert again.json()["row"]["id"] == first.json()["row"]["id"]
    returned = scan(client, auth_headers, fabric_batch, "returned")
    assert returned.status_code == 200, returned.text
    assert fingerprint() == before
    report = client.get("/api/fabric-scans", headers=auth_headers).json()
    assert (report["total"], report["received"], report["returned"]) == (2, 1, 1)
    assert report["summary"][0]["batch_no"] == "DAILY-ROLLS"
    assert report["rows"][0]["operator_name"]


def test_return_without_receipt_and_depleted_batch(client, auth_headers, fabric_batch):
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        batch.quantity = 0
        batch.archived_at = datetime.now(timezone.utc)
        db.commit()
    before = fingerprint()
    response = scan(client, auth_headers, fabric_batch, "returned")
    assert response.status_code == 200, response.text
    assert fingerprint() == before


@pytest.mark.parametrize("code", ["123", "B1-R0", "B1-R-1", "B1-R2147483648", "/inventory?batch_id=1", "/packages?batch_id=1&roll=1", "/inventory?batch_id=1&batch_id=2&roll=1", "javascript:/inventory?batch_id=1&roll=1"])
def test_invalid_roll_codes(client, auth_headers, code):
    response = scan(client, auth_headers, 1, code=code)
    assert response.status_code == 400, response.text
    with TestSessionLocal() as db:
        assert db.query(FabricScan).count() == 0


def test_unknown_roll_and_non_fabric_rejected(client, auth_headers, fabric_batch):
    assert scan(client, auth_headers, fabric_batch, code=f"B{fabric_batch}-R4").status_code == 400
    assert scan(client, auth_headers, 2147483647).status_code == 404
    with TestSessionLocal() as db:
        batch = db.get(StockBatch, fabric_batch)
        batch.item.category = "accessory"
        db.commit()
    assert scan(client, auth_headers, fabric_batch).status_code == 404


def test_tashkent_midnight_and_historical_report(client, auth_headers, fabric_batch, monkeypatch):
    monkeypatch.setattr(fabric_scans, "now_utc", lambda: datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc))
    first = scan(client, auth_headers, fabric_batch).json()
    assert first["row"]["report_date"] == "2026-09-11"
    monkeypatch.setattr(fabric_scans, "now_utc", lambda: datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc))
    second = scan(client, auth_headers, fabric_batch).json()
    assert second["row"]["report_date"] == "2026-09-12"
    assert second["duplicate"] is False
    for day in ["2026-09-11", "2026-09-12"]:
        assert client.get(f"/api/fabric-scans?report_date={day}", headers=auth_headers).json()["received"] == 1


def test_summary_is_not_paginated_and_snapshots_survive_catalog_edits(client, auth_headers, fabric_batch):
    for roll in range(1, 4):
        assert scan(client, auth_headers, fabric_batch, code=f"B{fabric_batch}-R{roll}").status_code == 200
    with TestSessionLocal() as db:
        db.get(StockBatch, fabric_batch).batch_no = "RENAMED"
        db.commit()
    report = client.get("/api/fabric-scans?page_size=1&page=2", headers=auth_headers).json()
    assert len(report["rows"]) == 1
    assert report["received"] == 3
    assert report["summary"][0]["received"] == 3
    assert report["rows"][0]["batch_no"] == "DAILY-ROLLS"


@pytest.mark.parametrize("permission,can_scan,can_read", [
    ("cutting.records", True, True), ("cutting.bundles", True, True),
    ("storage.receive", True, True), ("storage.items", True, True),
    ("management.view", False, True), ("planning.production", False, True),
    ("sales.orders", False, False),
])
def test_permissions(client, fabric_batch, permission, can_scan, can_read):
    user = User(id=987, name="Test worker", factory_code="MIL", extra_permissions=[])
    user.role = Role(name="Test", permissions=[permission])
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        assert scan(client, {}, fabric_batch).status_code == (200 if can_scan else 403)
        assert client.get("/api/fabric-scans").status_code == (200 if can_read else 403)
    finally:
        app.dependency_overrides.pop(get_current_user)


def test_factory_isolation_and_server_owned_fields(client, auth_headers, fabric_batch):
    assert scan(client, auth_headers, fabric_batch).status_code == 200
    user = User(id=987, name="Eco worker", factory_code="ECO", extra_permissions=[])
    user.role = Role(name="Cutting", permissions=["cutting.records"])
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        assert client.get("/api/fabric-scans").json()["total"] == 0
        assert scan(client, {}, fabric_batch).json()["duplicate"] is False
        assert client.get("/api/fabric-scans").json()["department"] == "ECT"
        response = client.post("/api/fabric-scans", json={"code": f"B{fabric_batch}-R2", "direction": "received", "department": "CUT", "report_date": "2020-01-01"})
        assert response.status_code == 422
        user.factory_code = "BST"
        assert client.get("/api/fabric-scans").status_code == 403
        assert scan(client, {}, fabric_batch).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user)


def test_unauthenticated_requests_rejected(client, fabric_batch):
    assert client.get("/api/fabric-scans").status_code == 401
    assert scan(client, {}, fabric_batch).status_code == 401


def test_simultaneous_scans_count_one_roll(client, auth_headers, fabric_batch):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scan(client, auth_headers, fabric_batch), range(2)))
    assert all(response.status_code == 200 for response in results)
    assert sorted(response.json()["duplicate"] for response in results) == [False, True]
    with TestSessionLocal() as db:
        assert db.query(FabricScan).count() == 1


def test_migration_creates_only_register_and_reverses():
    path = Path(__file__).parents[2] / "alembic/versions/0123_fabric_scan_register.py"
    spec = importlib.util.spec_from_file_location("fabric_scan_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert inspect(connection).get_table_names() == ["fabric_scans"]
            assert inspect(connection).get_foreign_keys("fabric_scans") == []
            assert len(inspect(connection).get_unique_constraints("fabric_scans")) == 1
            migration.downgrade()
            assert inspect(connection).get_table_names() == []
    engine.dispose()
