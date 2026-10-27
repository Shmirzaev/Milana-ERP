from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, text
from sqlalchemy.orm import joinedload, sessionmaker

from app.api.routes.fabric_scans import router
from app.core.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.libs.dto.inventory.fabric_scan_input import ScanInput
from app.libs.dto.inventory.fabric_scan_output import FabricScanRowOut
from app.libs.enums.inventory import FabricScanDirection
from app.models.inventory import fabric_scans_service as service
from app.schemas import FabricScan, Item, Role, StockBatch, StockMovement, User, Warehouse
from app.schemas.inventory.fabric_scan_persistence import add_fabric_scan
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable,
    create_target_database,
    finalize_target,
    load_approved_instance,
    require_or_skip,
    target_engine,
)

engine = None
Sessions = sessionmaker(autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="module")
def migrated_database():
    """Actual Alembic head in exactly one approved, owned disposable PG database."""
    global engine
    try:
        instance = load_approved_instance()
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    target_engine_handle = None
    try:
        target_engine_handle = target_engine(
            target,
            options="-c timezone=UTC -c statement_timeout=20000 -c lock_timeout=8000",
        )
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                settings,
                "DATABASE_URL",
                target_engine_handle.url.render_as_string(hide_password=False).replace("%", "%%"),
            )
            patch.setattr(sa, "engine_from_config", lambda *args, **kwargs: target_engine_handle)
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            command.upgrade(config, "head")
        engine = target_engine_handle
        Sessions.configure(bind=engine)
        assert engine.dialect.name == "postgresql"
        with engine.connect() as connection:
            assert connection.execute(text("SHOW TIME ZONE")).scalar_one() == "UTC"
            assert connection.execute(text("SELECT current_database() <> 'postgres'")).scalar_one()
        yield engine
    finally:
        Sessions.configure(bind=None)
        engine, target_engine_handle = None, target_engine_handle
        finalize_target(target, target_engine_handle)


@pytest.fixture(autouse=True)
def pg_case(migrated_database):
    """Reset only this disposable database and seed a real fabric roll and actor."""
    with migrated_database.begin() as connection:
        connection.exec_driver_sql(
            "TRUNCATE fabric_scans, stock_movements, stock_batches, items, warehouses, users, roles "
            "RESTART IDENTITY CASCADE"
        )
    with Sessions.begin() as db:
        role = Role(name="Fabric scan PG worker", permissions=["cutting.records"])
        warehouse = Warehouse(name="Fabric scan PG warehouse", type="fabric")
        item = Item(sku="FABRIC-SCAN-PG", name="PG cotton", category="fabric", unit="kg")
        db.add_all([role, warehouse, item])
        db.flush()
        user = User(
            name="PG scanner", email="fabric-scan-pg@example.invalid", password_hash="unused",
            role_id=role.id, factory_code="MIL", is_active=True,
        )
        batch = StockBatch(
            item_id=item.id, warehouse_id=warehouse.id, batch_no="PG-ROLLS", quantity=45,
            piece_count=3, roll_weights_kg=[10, 15, 20], unit="kg", color="Blue",
        )
        db.add_all([user, batch])
        db.flush()
        seeded = {"user": user.id, "batch": batch.id, "item": item.id}
    yield seeded


def _counts():
    with Sessions() as db:
        return db.query(FabricScan).count(), db.query(StockMovement).count()


def _stock_snapshot(batch_id):
    with Sessions() as db:
        batch = db.get(StockBatch, batch_id)
        return (batch.quantity, batch.piece_count, tuple(batch.roll_weights_kg or ()), batch.archived_at)


def _route_client(user_id):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def db_override():
        with Sessions() as db:
            yield db

    def actor_override():
        with Sessions() as db:
            user = db.query(User).options(joinedload(User.role)).filter(User.id == user_id).one()
            _ = user.role.permissions
            db.expunge_all()
            return user

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_current_user] = actor_override
    return TestClient(app, raise_server_exceptions=False)


def _post(client, batch_id, direction="received"):
    return client.post("/api/fabric-scans", json={"code": f"B{batch_id}-R1", "direction": direction})


def test_pg_concurrent_same_day_duplicate_uses_unique_violation_recovery(pg_case, monkeypatch):
    """Two separate sessions stage the same identity; PG's real unique index elects one."""
    before_stock = _stock_snapshot(pg_case["batch"])
    before_counts = _counts()
    staged = Barrier(2)
    real_writer = add_fabric_scan
    real_now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "now_utc", lambda: real_now)

    def synchronized_writer(db, command):
        row = real_writer(db, command)
        staged.wait(timeout=8)
        return row

    monkeypatch.setattr(service, "add_fabric_scan", synchronized_writer)
    observed_sqlstates = []

    def record_database_error(exception_context):
        original = exception_context.original_exception
        diagnostic = getattr(original, "diag", None)
        state = getattr(diagnostic, "sqlstate", None) or getattr(original, "pgcode", None)
        if state:
            observed_sqlstates.append(state)

    event.listen(engine, "handle_error", record_database_error)

    def scan_once():
        with Sessions() as db:
            pid = db.execute(text("SELECT pg_backend_pid()")).scalar_one()
            user = db.query(User).options(joinedload(User.role)).filter(User.id == pg_case["user"]).one()
            result = service.scan_fabric_roll(db, ScanInput(code=f"B{pg_case['batch']}-R1", direction="received"), user)
            return pid, result

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(scan_once) for _ in range(2)]
            outcomes = [future.result(timeout=25) for future in futures]
    finally:
        event.remove(engine, "handle_error", record_database_error)
    assert outcomes[0][0] != outcomes[1][0], "workers must use independent PostgreSQL connections"
    results = [outcome[1] for outcome in outcomes]
    assert sorted(result.duplicate for result in results) == [False, True]
    assert results[0].row.id == results[1].row.id
    assert observed_sqlstates.count("23505") == 1, observed_sqlstates
    with Sessions() as db:
        assert db.query(FabricScan).count() == 1
        assert db.query(FabricScan).one().direction == "received"
    assert _counts() == (before_counts[0] + 1, before_counts[1])
    assert _stock_snapshot(pg_case["batch"]) == before_stock


def test_pg_tashkent_midnight_route_payload_and_history(pg_case, monkeypatch):
    before_stock = _stock_snapshot(pg_case["batch"])
    before_movements = _counts()[1]
    client = _route_client(pg_case["user"])
    try:
        monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc))
        first = _post(client, pg_case["batch"]).json()
        monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc))
        second = _post(client, pg_case["batch"]).json()
        assert first["duplicate"] is False and second["duplicate"] is False
        assert first["row"]["report_date"] == "2026-09-11"
        assert second["row"]["report_date"] == "2026-09-12"
        assert first["row"]["scanned_at"] == "2026-09-11T18:59:59+00:00"
        assert second["row"]["scanned_at"] == "2026-09-11T19:00:00+00:00"
        for day in ("2026-09-11", "2026-09-12"):
            report = client.get(f"/api/fabric-scans?report_date={day}").json()
            assert (report["report_date"], report["total"], report["received"]) == (day, 1, 1)
        with Sessions() as db:
            stored = db.query(FabricScan).order_by(FabricScan.report_date).all()
            assert [row.scanned_at for row in stored] == [
                datetime(2026, 9, 11, 18, 59, 59, tzinfo=timezone.utc),
                datetime(2026, 9, 11, 19, 0, tzinfo=timezone.utc),
            ]
        assert _stock_snapshot(pg_case["batch"]) == before_stock
        assert _counts()[1] == before_movements
    finally:
        client.close()


def test_pg_duplicate_replay_precedes_missing_batch_lookup(pg_case, monkeypatch):
    monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))
    client = _route_client(pg_case["user"])
    try:
        first = _post(client, pg_case["batch"]).json()
        with Sessions.begin() as db:
            db.query(StockBatch).filter(StockBatch.id == pg_case["batch"]).delete(synchronize_session=False)
        counts_after_batch_removal = _counts()
        replay = _post(client, pg_case["batch"]).json()
        assert first["duplicate"] is False
        assert replay == {"duplicate": True, "row": first["row"]}
        assert counts_after_batch_removal == (1, 0)
        assert _counts() == counts_after_batch_removal
        with Sessions() as db:
            assert db.get(StockBatch, pg_case["batch"]) is None
            row = db.query(FabricScan).one()
            assert (row.fabric_name, row.batch_no, row.color, row.operator_name) == ("PG cotton", "PG-ROLLS", "Blue", "PG scanner")
    finally:
        client.close()


@pytest.mark.parametrize("factory_code,expected_department", [("MIL", "CUT"), ("ECO", "ECT"), ("BST", None)])
def test_pg_factory_scope_cut_ect_and_bad_factory_guard(pg_case, factory_code, expected_department, monkeypatch):
    monkeypatch.setattr(service, "now_utc", lambda: datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc))
    with Sessions.begin() as db:
        role = db.query(Role).one()
        actor = User(
            name=f"{factory_code} scanner", email=f"{factory_code.lower()}-scan@example.invalid",
            password_hash="unused", role_id=role.id, factory_code=factory_code, is_active=True,
        )
        db.add(actor)
        db.flush()
        actor_id = actor.id
    client = _route_client(actor_id)
    try:
        response = _post(client, pg_case["batch"])
        if expected_department is None:
            assert response.status_code == 403
            assert response.json()["detail"]
            with Sessions() as db:
                assert db.query(FabricScan).count() == 0
        else:
            assert response.status_code == 200, response.text
            expected_row = {
                "id": response.json()["row"]["id"],
                "report_date": "2026-09-11",
                "direction": "received",
                "fabric_name": "PG cotton",
                "batch_no": "PG-ROLLS",
                "color": "Blue",
                "roll_number": 1,
                "operator_name": f"{factory_code} scanner",
                "scanned_at": "2026-09-11T18:00:00+00:00",
            }
            assert response.json() == {"duplicate": False, "row": expected_row}
            # Department belongs to the report envelope and persisted row, not the POST row DTO.
            assert client.get("/api/fabric-scans").json()["department"] == expected_department
            with Sessions() as db:
                assert db.query(FabricScan).one().department == expected_department
    finally:
        client.close()


@pytest.mark.parametrize("case,expected", [
    ("naive", "2026-09-11T18:59:59+00:00"),
    ("utc", "2026-09-11T18:59:59+00:00"),
    ("offset", "2026-09-11T18:59:59+05:30"),
])
def test_timestamp_projection_has_literal_legacy_oracles(pg_case, case, expected):
    """Projection-only contract checks; no naïve/NULL timestamptz storage is claimed."""
    stamp = datetime(2026, 9, 11, 18, 59, 59)
    if case == "utc":
        stamp = stamp.replace(tzinfo=timezone.utc)
    elif case == "offset":
        from datetime import timedelta
        stamp = stamp.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    row = SimpleNamespace(
        id=7, report_date=date(2026, 9, 11), direction="received", fabric_name="Cotton",
        batch_no="B-1", color="Blue", roll_number=1, operator_name="Scanner", scanned_at=stamp,
    )
    projected = service.row_data(row)
    assert projected.model_dump(mode="json")["scanned_at"] == expected


def test_timestamp_dto_rejects_null_projection_only(pg_case):
    with pytest.raises(ValidationError):
        FabricScanRowOut(
            id=7, report_date=date(2026, 9, 11), direction=FabricScanDirection.RECEIVED,
            fabric_name="Cotton", batch_no="B-1", color="Blue", roll_number=1,
            operator_name="Scanner", scanned_at=None,
        )



