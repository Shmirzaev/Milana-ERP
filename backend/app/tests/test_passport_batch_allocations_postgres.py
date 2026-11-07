"""Owned PostgreSQL: grouped save/confirm, row locks, retries and recovery."""
import os
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.router import api_router
from app.api.routes import production
from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.schemas import (
    AuditLog, Bundle, CuttingMaterialUsage, CuttingPassport, CuttingRecord, Department, Item,
    MaterialReservation, Model, ModelSize, ProductionBatch, ProductionOrder, ProductionOrderItem,
    ProductionOrderMaterial, StockBatch, StockMovement, User, Warehouse, WasteRecord, WorkOrder,
)


@pytest.fixture(scope="module")
def allocation_postgres():
    raw = os.environ.get("PASSPORT_ALLOCATION_POSTGRES_URL")
    if not raw:
        pytest.skip("Set PASSPORT_ALLOCATION_POSTGRES_URL to an owned disposable loopback database")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Grouped passport tests require owned loopback PostgreSQL without overrides")
    schema = f"passport_allocations_{uuid4().hex}"
    engine = create_engine(url, pool_size=10, max_overflow=0,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=12000"})
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        Base.metadata.create_all(engine)
        # Catalog's existing0084 generated read columns are absent from ORM
        # create_all; reproduce that historical DDL only in this owned schema.
        path = Path(__file__).parents[2] / "alembic/versions/0084_model_group_key.py"
        spec = importlib.util.spec_from_file_location("qa_allocation_0084", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE models ADD COLUMN is_legacy_import boolean GENERATED ALWAYS AS ((coalesce(details_json ->> 'legacy_import', 'false')) = 'true') STORED")
            conn.exec_driver_sql(f"ALTER TABLE models ADD COLUMN model_group_key text GENERATED ALWAYS AS ({migration.GROUP_KEY_SQL}) STORED")
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        app = FastAPI()
        app.include_router(api_router)
        def db_context():
            with sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_context
        yield sessions, engine, app
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def make_case(sessions):
    marker = uuid4().hex[:10]
    with sessions() as db:
        depts = {row.code: row.id for row in db.query(Department)}
        for code in ("CUT", "MIL", "PKG", "FGS", "STR"):
            if code not in depts:
                dept = Department(code=code, name=code); db.add(dept); db.flush(); depts[code] = dept.id
        actor = User(name="QA allocation actor", email=f"allocation-{marker}@example.com", password_hash="unused",
                     factory_code="MIL", extra_permissions=["*"], is_active=True,
                     last_seen_at=datetime.now(timezone.utc))
        item = Item(sku=f"ALLOC-{marker}", name="QA red fabric", category="fabric", unit="kg")
        warehouse = Warehouse(name=f"QA warehouse {marker}", type="fabric_storage", department_id=depts["STR"])
        model = Model(code=f"QA-{marker}-V1", name="QA allocation model", status="approved")
        db.add_all([actor, item, warehouse, model]); db.flush()
        db.add(ModelSize(model_id=model.id, size="S"))
        batches = []
        for label, stock in (("A", 150), ("B", 250)):
            batch = StockBatch(item_id=item.id, batch_no=f"QA-{marker}-{label}", color="red", width=1.6, gsm=.18,
                quantity=stock, unit="kg", warehouse_id=warehouse.id, qc_status="passed", cost_per_unit=3)
            db.add(batch); db.flush(); batches.append(batch)
            db.add(StockMovement(movement_type="receive", item_id=item.id, batch_id=batch.id, to_warehouse_id=warehouse.id,
                                 quantity=stock, unit="kg", created_by=actor.id))
        order = ProductionOrder(production_no=f"QA-ALLOC-{marker}", production_type="branded_stock", model_id=model.id,
                                status="cutting", planned_quantity=600, created_by=actor.id)
        db.add(order); db.flush()
        db.add(ProductionOrderItem(production_order_id=order.id, model_id=model.id, color="red", size="S", planned_quantity=600))
        db.add(ProductionBatch(production_order_id=order.id, batch_index=1, batch_no=f"QA-N-{marker}", name="Nastil 1", planned_quantity=600))
        for index, (batch, quantity) in enumerate(zip(batches, (100, 200)), 1):
            db.add(ProductionOrderMaterial(production_order_id=order.id, stock_batch_id=batch.id, estimated_quantity=quantity, unit="kg", position=index))
            db.add(MaterialReservation(reservation_no=f"QA-R-{marker}-{index}", production_order_id=order.id, item_id=item.id,
                stock_batch_id=batch.id, warehouse_id=warehouse.id, reserved_quantity=quantity, consumed_quantity=0, released_quantity=0,
                unit="kg", source="planning", reservation_type="material", status="reserved", reserved_by=actor.id))
        works = {}
        for op, code in (("cutting", "CUT"), ("sewing", "MIL"), ("packaging", "PKG"), ("storage_transfer", "FGS")):
            work = WorkOrder(production_order_id=order.id, department_id=depts[code], operation=op,
                status="in_progress" if op == "cutting" else "waiting", planned_input_qty=600, planned_output_qty=600)
            db.add(work); db.flush(); works[op] = work.id
        db.commit()
        bid = [batch.id for batch in batches]
        payload = {"date": "2026-11-05T00:00:00Z", "production_order_id": order.id,
                   "materials": [{"stock_batch_id": bid[0], "batch_allocations": [
                       {"stock_batch_id": batch_id, "quantity": amount} for batch_id, amount in zip(bid, (100, 200))],
                       "layer_weight_kg": 3, "total_layers": 100, "pieces": 600, "rolls_count": 3, "waste_pct": 10}]}
        return {"order": order.id, "batches": bid, "works": works, "actor": actor.id, "payload": payload,
                "headers": {"Authorization": f"Bearer {create_access_token(actor.id, extra={'factory_code': 'MIL'})}"}}


def save(app, case):
    with TestClient(app) as client:
        return client.post("/api/cutting-passports", headers=case["headers"], json=case["payload"])


def confirm(app, case, passport):
    with TestClient(app) as client:
        return client.post("/api/cutting/records", headers=case["headers"], json={
            "work_order_id": case["works"]["cutting"], "cutting_passport_id": passport["id"],
            "production_batch_id": passport["production_batch_id"], "use_passport_materials": True,
            "input_quantity": 0, "cut_pieces": 600, "passed_pieces": 600,
            "bundles": [{"color": "red", "size": "S", "quantity": 600, "count": 1, "next": "sewing", "sewing_factory": "milana"}],
        })


def test_real_http_save_and_four_competing_confirm_retries_debit_once(allocation_postgres):
    sessions, _, app = allocation_postgres
    case = make_case(sessions)
    saved = save(app, case)
    assert saved.status_code == 201, saved.text
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: confirm(app, case, saved.json()), range(4)))
    assert sorted(row.status_code for row in results) == [201, 409, 409, 409], [row.text for row in results]
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [50, 50]
        assert db.query(CuttingRecord).filter_by(work_order_id=case["works"]["cutting"]).count() == 1
        assert db.query(Bundle).filter_by(production_order_id=case["order"]).one().quantity == 600
        usages = db.query(CuttingMaterialUsage).join(CuttingRecord).filter(CuttingRecord.work_order_id == case["works"]["cutting"]).all()
        assert sum(row.details["cut_pieces"] for row in usages) == 600
        assert sum(row.details["material_rolls_used"] for row in usages) == 3
        assert sum(float(row.quantity) for row in db.query(WasteRecord).filter_by(work_order_id=case["works"]["cutting"])) == 30
        assert sorted(float(row.consumed_quantity) for row in db.query(MaterialReservation).filter_by(production_order_id=case["order"])) == [100, 200]
        audit = db.query(AuditLog).filter_by(entity_type="CuttingRecord").order_by(AuditLog.id.desc()).first()
        assert audit.entry_hash


def test_group_save_waits_for_source_lock_then_recovers_without_debit(allocation_postgres):
    sessions, engine, app = allocation_postgres
    case = make_case(sessions)
    entered = Event()
    def capture(conn, cursor, statement, parameters, context, many):
        if "FOR UPDATE OF stock_batches" in statement:
            entered.set()
    with sessions() as holder:
        holder.query(StockBatch).filter_by(id=case["batches"][1]).with_for_update(of=StockBatch).one()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(save, app, case)
                assert entered.wait(3)
                assert not future.done()
                holder.rollback()
                result = future.result(timeout=10)
            assert result.status_code == 201, result.text
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]


def test_second_source_fault_rolls_back_first_debit_record_and_audit_then_retry_recovers(allocation_postgres, monkeypatch):
    sessions, _, app = allocation_postgres
    case = make_case(sessions)
    saved = save(app, case)
    assert saved.status_code == 201, saved.text
    real_consume = production.consume_cutting_materials
    def fail(db, **kwargs):
        if kwargs["lines"][0]["stock_batch_id"] == case["batches"][1]:
            raise RuntimeError("injected second-source fault")
        return real_consume(db, **kwargs)
    monkeypatch.setattr(production, "consume_cutting_materials", fail)
    with pytest.raises(RuntimeError, match="injected second-source fault"):
        confirm(app, case, saved.json())
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]
        assert db.query(CuttingRecord).filter_by(work_order_id=case["works"]["cutting"]).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=case["order"]).count() == 0
        assert all(row.consumed_quantity == 0 for row in db.query(MaterialReservation).filter_by(production_order_id=case["order"]))
    monkeypatch.setattr(production, "consume_cutting_materials", real_consume)
    assert confirm(app, case, saved.json()).status_code == 201


def test_group_keeps_per_source_pending_shortage_evidence(allocation_postgres):
    sessions, _, app = allocation_postgres
    case = make_case(sessions)
    saved = save(app, case)
    assert saved.status_code == 201, saved.text
    with sessions() as db:
        db.get(StockBatch, case["batches"][0]).quantity = 0
        db.commit()
    response = confirm(app, case, saved.json())
    assert response.status_code == 201, response.text
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [0, 50]
        usage = db.query(CuttingMaterialUsage).filter_by(cutting_record_id=response.json()["id"], stock_batch_id=case["batches"][0]).one()
        assert usage.details["inventory_consumption"]["pending_quantity"] == 100
        assert usage.details["passport_material_group"]["anchor_stock_batch_id"] == case["batches"][0]
        assert db.query(Bundle).filter_by(production_order_id=case["order"]).one().quantity == 600


@pytest.mark.parametrize("linked_id_supplied", [False, True])
def test_real_http_raw_batch_amount_override_cannot_bypass_grouped_nastil(allocation_postgres, linked_id_supplied):
    sessions, _, app = allocation_postgres
    case = make_case(sessions)
    saved = save(app, case)
    assert saved.status_code == 201, saved.text
    payload = {"work_order_id": case["works"]["cutting"], "production_batch_id": saved.json()["production_batch_id"],
        "input_quantity": 0, "cut_pieces": 600, "passed_pieces": 600, "use_passport_materials": False,
        "materials": [{"stock_batch_id": bid, "quantity": 100, "unit": "kg"} for bid in case["batches"]],
        "bundles": [{"color": "red", "size": "S", "quantity": 600, "count": 1, "next": "sewing", "sewing_factory": "milana"}]}
    if linked_id_supplied: payload["cutting_passport_id"] = saved.json()["id"]
    with TestClient(app) as client:
        result = client.post("/api/cutting/records", headers=case["headers"], json=payload)
    assert result.status_code == 409, result.text
    with sessions() as db:
        assert [float(db.get(StockBatch, bid).quantity) for bid in case["batches"]] == [150, 250]
        assert db.query(CuttingRecord).filter_by(work_order_id=case["works"]["cutting"]).count() == 0
        assert db.query(Bundle).filter_by(production_order_id=case["order"]).count() == 0


def test_long_canonical_source_labels_survive_save_and_replacement_with_scalar_limit(allocation_postgres):
    sessions, _, app = allocation_postgres
    case = make_case(sessions)
    with sessions() as db:
        db.get(StockBatch, case["batches"][0]).batch_no = "A" * 35
        db.get(StockBatch, case["batches"][1]).batch_no = "B" * 35
        db.commit()
    saved = save(app, case)
    assert saved.status_code == 201, saved.text
    assert len(saved.json()["lot_no"]) <= 64
    assert [part["batch_no"] for part in saved.json()["materials"][0]["batch_allocations"]] == ["A" * 35, "B" * 35]
    with sessions() as db:
        original = db.get(StockBatch, case["batches"][1])
        replacement = StockBatch(item_id=original.item_id, batch_no="C" * 63, color="red", width=1.6, gsm=.18,
            quantity=250, unit="kg", warehouse_id=original.warehouse_id, qc_status="passed", cost_per_unit=3)
        db.add(replacement); db.flush()
        replacement_id = replacement.id
        db.add(StockMovement(movement_type="receive", item_id=replacement.item_id, batch_id=replacement.id,
            to_warehouse_id=replacement.warehouse_id, quantity=250, unit="kg", created_by=case["actor"]))
        db.commit()
    with TestClient(app) as client:
        response = client.patch(f"/api/work-orders/{case['works']['cutting']}/cutting-materials/{case['batches'][1]}",
                                headers=case["headers"], json={"stock_batch_id": replacement_id})
    assert response.status_code == 200, response.text
    with sessions() as db:
        passport = db.get(CuttingPassport, saved.json()["id"])
        assert len(passport.lot_no) <= 64
        assert [part["batch_no"] for part in passport.materials[0]["batch_allocations"]] == ["A" * 35, "C" * 63]
        assert [part["quantity"] for part in passport.materials[0]["batch_allocations"]] == [100, 200]
