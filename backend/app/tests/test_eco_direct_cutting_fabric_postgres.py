"""Owned PostgreSQL: identity registration races and physical ECO debit integrity."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Barrier
import importlib.util

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.router import api_router
from app.db.base import Base
from app.db.session import get_db
from app.schemas import CuttingRecord, MaterialReservation, StockBatch, StockMovement, WorkOrder
from app.schemas.inventory.eco_inventory import EcoMaterialBatch, EcoMaterialMovement
from app.tests.eco_fabric_fixture import make_eco_fabric_case, planning_payload
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, require_or_skip, target_engine, verify_approved_instance,
)


@pytest.fixture(scope="module")
def eco_postgres():
    try:
        instance = load_approved_instance()
        verify_approved_instance(instance)
    except ApprovedInstanceUnavailable as error:
        require_or_skip(error)
    target = create_target_database(instance)
    engine = None
    try:
        engine = target_engine(target, options="-clock_timeout=8000 -cstatement_timeout=15000")
        Base.metadata.create_all(engine)
        path = Path(__file__).parents[2] / "alembic/versions/0084_model_group_key.py"
        spec = importlib.util.spec_from_file_location("qa_eco_0084", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED")
            connection.exec_driver_sql(f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({migration.GROUP_KEY_SQL}) STORED")
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        app = FastAPI()
        app.include_router(api_router)
        def db_context():
            with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_context
        yield sessions, app
    finally:
        finalize_target(target, engine)


def post(app, url, headers, payload):
    with TestClient(app) as client:
        return client.post(url, headers=headers, json=payload)


def save_for_cut(app, sessions, case, quantity):
    order = post(app, "/api/planning/create-branded-production", case["mil_headers"], planning_payload(case))
    assert order.status_code == 201, order.text
    order = order.json()
    with sessions() as db:
        work = db.query(WorkOrder).filter_by(production_order_id=order["id"], operation="cutting").one().id
    passport = post(app, "/api/cutting-passports", case["eco_headers"], {
        "date": "2026-11-13T00:00:00Z", "production_order_id": order["id"],
        "materials": [{"stock_batch_id": order["fabric_batch_id"], "planned_kg": quantity, "pieces": 10}],
    })
    assert passport.status_code == 201, passport.text
    passport = passport.json()
    return {"work_order_id": work, "cutting_passport_id": passport["id"], "production_batch_id": passport["production_batch_id"],
        "use_passport_materials": True, "input_quantity": 0, "cut_pieces": 10, "passed_pieces": 10,
        "bundles": [{"color": "white", "size": "46", "quantity": 10, "count": 1, "next": "sewing", "sewing_factory": "eco_cotton"}]}


def test_four_competing_identity_registrations_create_one_zero_balance_bridge(eco_postgres):
    sessions, app = eco_postgres
    case = make_eco_fabric_case(sessions)
    barrier = Barrier(4)
    def create():
        barrier.wait(timeout=5)
        return post(app, "/api/planning/create-branded-production", case["mil_headers"], planning_payload(case))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [future.result(timeout=20) for future in [pool.submit(create) for _ in range(4)]]
    assert all(row.status_code in (201, 409) for row in results), [(row.status_code, row.text) for row in results]
    assert any(row.status_code == 201 for row in results)
    with sessions() as db:
        receipt = db.get(EcoMaterialBatch, case["receipt"])
        assert receipt.quantity == 100 and receipt.reserved_quantity == 10
        assert receipt.source_stock_batch_id
        assert db.query(StockBatch).filter_by(internal_batch_no=f"ECO-DIRECT-{case['receipt']}").count() == 1
        assert db.get(StockBatch, receipt.source_stock_batch_id).quantity == 0
        assert db.query(StockMovement).filter_by(batch_id=receipt.source_stock_batch_id).count() == 0
        assert db.query(MaterialReservation).filter_by(stock_batch_id=receipt.source_stock_batch_id).count() == 0


def test_two_real_cuts_cannot_overspend_shared_direct_receipt_and_retry_is_safe(eco_postgres):
    sessions, app = eco_postgres
    case = make_eco_fabric_case(sessions)
    payloads = [save_for_cut(app, sessions, case, 60) for _ in range(2)]
    barrier = Barrier(2)
    def confirm(payload):
        barrier.wait(timeout=5)
        return post(app, "/api/cutting/records", case["eco_headers"], payload)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=20) for future in [pool.submit(confirm, payload) for payload in payloads]]
    assert sorted(result.status_code for result in results) == [201, 409], [(row.status_code, row.text) for row in results]
    with sessions() as db:
        receipt = db.get(EcoMaterialBatch, case["receipt"])
        assert receipt.quantity == Decimal("40") and receipt.reserved_quantity == 10
        assert db.get(StockBatch, receipt.source_stock_batch_id).quantity == 0
        assert db.query(StockMovement).filter_by(batch_id=receipt.source_stock_batch_id).count() == 0
        assert db.query(EcoMaterialMovement).filter_by(batch_id=receipt.id, kind="consume").count() == 1
        assert db.query(CuttingRecord).filter(CuttingRecord.work_order_id.in_([p["work_order_id"] for p in payloads])).count() == 1
    for payload in payloads:
        assert post(app, "/api/cutting/records", case["eco_headers"], payload).status_code in (400, 409)
    with sessions() as db:
        assert db.get(EcoMaterialBatch, case["receipt"]).quantity == 40
