"""Focused persistence and wire-parity tests for the existing scan register.

Run explicitly with pytest --noconftest. The fixture owns its SQLite database.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.deps import get_current_user, get_db
from app.db.base import Base
from app.libs.dto.inventory.fabric_scan_input import ScanInput
from app.libs.dto.inventory.fabric_scan_output import FabricScanRowOut
from app.libs.enums.inventory import FabricScanDepartment, FabricScanDirection
from app.libs.types.inventory import FabricScanCreateCommand
from app.models.inventory import fabric_scans_service as service
from app.schemas import Item, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory.fabric_scan import FabricScan
from app.schemas.inventory.fabric_scan_persistence import add_fabric_scan
from app.api.routes.fabric_scans import router


@pytest.fixture
def scan_case():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    with factory() as db:
        mil_role = Role(name="Scan MIL " + token, permissions=["storage.receive"])
        eco_role = Role(name="Scan ECO " + token, permissions=["storage.receive"])
        denied_role = Role(name="Scan denied " + token, permissions=["sales.orders"])
        mil = User(name="MIL operator", email=token + "@mil.invalid", password_hash="unused",
                   factory_code="MIL", role=mil_role)
        eco = User(name="ECO operator", email=token + "@eco.invalid", password_hash="unused",
                   factory_code="ECO", role=eco_role)
        denied = User(name="Denied operator", email=token + "@denied.invalid", password_hash="unused",
                      factory_code="MIL", role=denied_role)
        item = Item(sku="SCAN-" + token, name="Legacy cotton", category="fabric", unit="kg")
        warehouse = Warehouse(name="Scan warehouse " + token, type="fabric_storage")
        db.add_all([mil, eco, denied, item, warehouse])
        db.flush()
        batch = StockBatch(item_id=item.id, warehouse_id=warehouse.id, batch_no="SCAN-SNAPSHOT",
                           quantity=45, piece_count=3, roll_weights_kg=[10, 15, 20],
                           unit="kg", cost_per_unit=2, color="Blue")
        db.add(batch)
        db.commit()
        case = {"factory": factory, "batch_id": batch.id, "mil_id": mil.id,
                "eco_id": eco.id, "denied_id": denied.id, "item_id": item.id}
    yield case
    engine.dispose()


def test_schema_writer_attaches_one_typed_snapshot_without_transaction_actions(scan_case, monkeypatch):
    added = []
    original_add = Session.add

    def record_add(db, instance, *args, **kwargs):
        added.append(instance)
        return original_add(db, instance, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("scan persistence must leave transaction actions to its caller")

    with scan_case["factory"]() as db:
        command = FabricScanCreateCommand(
            department=FabricScanDepartment.CUT,
            report_date=datetime(2026, 9, 11, tzinfo=timezone.utc).date(),
            batch_id=scan_case["batch_id"], roll_number=2,
            direction=FabricScanDirection.RECEIVED, fabric_name="Snapshot fabric",
            batch_no="Snapshot batch", color=None, operator_id=1,
            operator_name="Snapshot operator",
            scanned_at=datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc),
        )
        with monkeypatch.context() as patch:
            patch.setattr(Session, "add", record_add)
            for name in ("begin", "begin_nested", "flush", "commit", "rollback"):
                patch.setattr(Session, name, forbidden)
            row = add_fabric_scan(db, command)
            assert object_session(row) is db
        assert added == [row]
        db.flush()
        persisted = db.get(FabricScan, row.id)
        assert (persisted.department, persisted.direction) == ("CUT", "received")
        assert (persisted.fabric_name, persisted.batch_no, persisted.operator_name) == (
            "Snapshot fabric", "Snapshot batch", "Snapshot operator"
        )


def test_actual_router_preserves_literal_scan_and_report_payloads_without_stock_writes(
    scan_case, monkeypatch
):
    fixed = datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: fixed)
    app = FastAPI()
    app.include_router(router)
    actor_id = {"value": scan_case["mil_id"]}

    def isolated_db():
        with scan_case["factory"]() as db:
            yield db

    def current_user():
        with scan_case["factory"]() as db:
            return db.get(User, actor_id["value"])

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    with scan_case["factory"]() as db:
        batch = db.get(StockBatch, scan_case["batch_id"])
        before_stock = (batch.quantity, batch.archived_at, batch.piece_count, list(batch.roll_weights_kg))
        before_movements = db.query(StockMovement).count()

    with TestClient(app) as client:
        code = f"B{scan_case['batch_id']}-R1"
        first = client.post("/fabric-scans", json={"code": code, "direction": "received"})
        assert first.status_code == 200, first.text
        first_json = first.json()
        assert first_json["duplicate"] is False
        row = first_json["row"]
        assert {key: row[key] for key in (
            "report_date", "direction", "fabric_name", "batch_no", "color", "roll_number", "operator_name"
        )} == {
            "report_date": "2026-09-11", "direction": "received", "fabric_name": "Legacy cotton",
            "batch_no": "SCAN-SNAPSHOT", "color": "Blue", "roll_number": 1,
            "operator_name": "MIL operator",
        }
        assert row["scanned_at"] == "2026-09-11T18:59:59+00:00"
        duplicate = client.post("/fabric-scans", json={"code": code, "direction": "received"})
        assert duplicate.status_code == 200 and duplicate.json() == first_json | {"duplicate": True}
        returned = client.post("/fabric-scans", json={"code": code, "direction": "returned"})
        assert returned.status_code == 200 and returned.json()["duplicate"] is False

        # The register is a snapshot: later catalog edits do not rewrite its row.
        with scan_case["factory"].begin() as db:
            db.get(Item, scan_case["item_id"]).name = "Renamed catalog item"
            db.get(StockBatch, scan_case["batch_id"]).batch_no = "RENAMED-BATCH"
        report = client.get("/fabric-scans?page=1&page_size=1")
        assert report.status_code == 200, report.text
        report_json = report.json()
        assert (report_json["report_date"], report_json["department"], report_json["total"],
                report_json["received"], report_json["returned"], report_json["page"],
                report_json["page_size"]) == ("2026-09-11", "CUT", 2, 1, 1, 1, 1)
        assert report_json["summary"] == [{"fabric_name": "Legacy cotton", "batch_no": "SCAN-SNAPSHOT",
                                            "color": "Blue", "received": 1, "returned": 1}]
        assert report_json["rows"][0]["fabric_name"] == "Legacy cotton"
        assert report_json["rows"][0]["batch_no"] == "SCAN-SNAPSHOT"

        actor_id["value"] = scan_case["eco_id"]
        eco_scan = client.post("/fabric-scans", json={"code": code, "direction": "returned"})
        assert eco_scan.status_code == 200
        assert client.get("/fabric-scans").json()["department"] == "ECT"

        actor_id["value"] = scan_case["denied_id"]
        denied = client.post("/fabric-scans", json={"code": "not-a-roll", "direction": "received"})
        assert denied.status_code == 403
        actor_id["value"] = scan_case["mil_id"]
        bad_department = client.post("/fabric-scans", json={
            "code": "not-a-roll", "direction": "received", "department": "CUT"
        })
        assert bad_department.status_code == 422
        invalid_direction = client.post("/fabric-scans", json={"code": code, "direction": "issued"})
        assert invalid_direction.status_code == 422
        invalid_roll = client.post("/fabric-scans", json={"code": "B1-R0", "direction": "received"})
        assert invalid_roll.status_code == 400

    with scan_case["factory"]() as db:
        batch = db.get(StockBatch, scan_case["batch_id"])
        assert (batch.quantity, batch.archived_at, batch.piece_count, list(batch.roll_weights_kg)) == before_stock
        assert db.query(StockMovement).count() == before_movements
        assert db.query(FabricScan).count() == 3


def test_nonfabric_and_roll_bound_refusals_keep_the_register_unchanged(scan_case):
    with scan_case["factory"]() as db:
        actor = db.get(User, scan_case["mil_id"])
        batch_id = scan_case["batch_id"]
        db.get(Item, scan_case["item_id"]).category = "accessory"
        db.commit()
        with pytest.raises(HTTPException) as category_error:
            service.scan_fabric_roll(db, ScanInput(code=f"B{batch_id}-R1", direction="received"), actor)
        assert getattr(category_error.value, "status_code", None) == 404
        db.get(Item, scan_case["item_id"]).category = "fabric"
        db.commit()
        with pytest.raises(HTTPException) as roll_error:
            service.scan_fabric_roll(db, ScanInput(code=f"B{batch_id}-R4", direction="received"), actor)
        assert getattr(roll_error.value, "status_code", None) == 400
        assert db.query(FabricScan).count() == 0


def test_department_guard_precedes_qr_parse_and_roll_count_uses_larger_snapshot(scan_case):
    with scan_case["factory"]() as db:
        mil = db.get(User, scan_case["mil_id"])
        mil.factory_code = "BST"
        with pytest.raises(HTTPException) as denied:
            service.scan_fabric_roll(db, ScanInput(code="not-a-roll", direction="received"), mil)
        assert denied.value.status_code == 403
        assert denied.value.detail == "Besttex does not have a cutting operation"
        mil.factory_code = "MIL"
        batch = db.get(StockBatch, scan_case["batch_id"])
        batch.piece_count = 1
        batch.roll_weights_kg = [10, 15, 20]
        db.commit()
        accepted = service.scan_fabric_roll(
            db, ScanInput(code=f"B{batch.id}-R3", direction="received"), mil
        )
        assert accepted.duplicate is False and accepted.row.roll_number == 3


def test_duplicate_replay_precedes_batch_lookup(scan_case, monkeypatch):
    monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, tzinfo=timezone.utc))
    with scan_case["factory"]() as db:
        actor = db.get(User, scan_case["mil_id"])
        payload = ScanInput(code=f"B{scan_case['batch_id']}-R1", direction="received")
        first = service.scan_fabric_roll(db, payload, actor)
        assert first.duplicate is False
        db.get(Item, scan_case["item_id"]).category = "accessory"
        db.commit()
        replay = service.scan_fabric_roll(db, payload, actor)
        assert replay.duplicate is True and replay.row.id == first.row.id
        assert db.query(FabricScan).count() == 1


def test_commit_integrityerror_without_duplicate_rolls_back_and_retry_succeeds(scan_case, monkeypatch):
    fixed = datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: fixed)
    def fail_commit(db):
        raise IntegrityError("insert fabric scan", {}, RuntimeError("forced integrity error"))

    with scan_case["factory"]() as db:
        actor = db.get(User, scan_case["mil_id"])
        with monkeypatch.context() as patch:
            patch.setattr(Session, "commit", fail_commit)
            with pytest.raises(IntegrityError, match="forced integrity error"):
                service.scan_fabric_roll(
                    db, ScanInput(code=f"B{scan_case['batch_id']}-R1", direction="received"), actor
                )
        assert db.query(FabricScan).count() == 0
        result = service.scan_fabric_roll(
            db, ScanInput(code=f"B{scan_case['batch_id']}-R1", direction="received"), actor
        )
        assert result.duplicate is False
        assert result.row.direction is FabricScanDirection.RECEIVED


@pytest.mark.parametrize("scanned_at", [
    "2026-09-11T18:59:59",
    "2026-09-11T18:59:59+00:00",
    "2026-09-11T23:59:59+05:30",
])
def test_row_datetime_json_keeps_datetime_isoformat_spelling(scanned_at: str):
    scanned_at = datetime.fromisoformat(scanned_at)
    row = FabricScanRowOut(
        id=7, report_date=datetime(2026, 9, 11).date(), direction=FabricScanDirection.RECEIVED,
        fabric_name="Independent snapshot", batch_no="B-7", color=None,
        roll_number=2, operator_name="Operator", scanned_at=scanned_at,
    )
    assert row.model_dump(mode="json")["scanned_at"] == scanned_at.isoformat()


def test_tashkent_midnight_creates_two_historical_daily_identities(scan_case, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    def isolated_db():
        with scan_case["factory"]() as db:
            yield db

    def current_user():
        with scan_case["factory"]() as db:
            return db.get(User, scan_case["mil_id"])

    app.dependency_overrides[get_db] = isolated_db
    app.dependency_overrides[get_current_user] = current_user
    with TestClient(app) as client:
        monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc))
        before_midnight = client.post("/fabric-scans", json={
            "code": f"B{scan_case['batch_id']}-R1", "direction": "received"
        })
        assert before_midnight.status_code == 200 and before_midnight.json()["duplicate"] is False
        assert before_midnight.json()["row"]["report_date"] == "2026-09-11"

        monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc))
        after_midnight = client.post("/fabric-scans", json={
            "code": f"B{scan_case['batch_id']}-R1", "direction": "received"
        })
        assert after_midnight.status_code == 200 and after_midnight.json()["duplicate"] is False
        assert after_midnight.json()["row"]["report_date"] == "2026-09-12"
        for report_date in ("2026-09-11", "2026-09-12"):
            report = client.get(f"/fabric-scans?report_date={report_date}")
            assert report.status_code == 200
            assert (report.json()["report_date"], report.json()["total"], report.json()["received"]) == (
                report_date, 1, 1
            )
    with scan_case["factory"]() as db:
        assert db.query(FabricScan).count() == 2
        assert db.query(StockMovement).count() == 0


def test_archived_depleted_batch_can_still_register_a_return_without_stock_mutation(
    scan_case, monkeypatch
):
    fixed = datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: fixed)
    with scan_case["factory"]() as db:
        actor = db.get(User, scan_case["mil_id"])
        batch = db.get(StockBatch, scan_case["batch_id"])
        batch.quantity = 0
        batch.archived_at = fixed
        db.commit()
        before = (batch.quantity, batch.archived_at)
        result = service.scan_fabric_roll(
            db, ScanInput(code=f"B{batch.id}-R1", direction="returned"), actor
        )
        assert result.duplicate is False
        assert (batch.quantity, batch.archived_at) == before
        assert db.query(StockMovement).count() == 0
