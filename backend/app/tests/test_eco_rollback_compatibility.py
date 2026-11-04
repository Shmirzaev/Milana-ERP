"""Exact active runtime + additive migrations; no ECO API/ORM registration.

SQLite runs offline. The opt-in CI gate repeats migration and cold lifespan
startup on one newly-created, job-owned PostgreSQL schema, never public DBs.
"""
import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import main
from app.db.base import Base
from app.db.eco_schema_compatibility import ECO_COLUMNS, PREDECESSOR, SUCCESSOR
from app.tests.test_startup_schema import _harden_runtime_settings


def config():
    return Config(str(main._alembic_config().config_file_name))


def prepare(engine, monkeypatch, *, migrate_predecessor=False):
    # This worktree registers exactly the active 11f80 ORM, not the ECO mappings.
    assert not set(ECO_COLUMNS).intersection(Base.metadata.tables)
    monkeypatch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
    if migrate_predecessor:
        # PostgreSQL runs the actual legacy chain through production's exact
        # 0150 revision, rather than manufacturing a schema from ORM metadata.
        command.upgrade(config(), PREDECESSOR)
    else:
        Base.metadata.create_all(engine)
        command.stamp(config(), PREDECESSOR)
    monkeypatch.setattr(main, "engine", engine)


def cold_start(monkeypatch):
    _harden_runtime_settings(monkeypatch)
    monkeypatch.setenv("RUN_SEED_ON_STARTUP", "false")
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


@pytest.fixture
def rollback_engine(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'rollback.db'}", connect_args={"check_same_thread": False})
    prepare(engine, monkeypatch)
    yield engine
    engine.dispose()


def test_canonical_graph_excludes_unreleased_hr():
    scripts = ScriptDirectory.from_config(config())
    assert scripts.get_heads() == [SUCCESSOR]
    assert set(scripts.get_revision(SUCCESSOR).down_revision) == {"0151_eco_accessory_approval", PREDECESSOR}
    assert all("gate_enrollment" not in revision.revision for revision in scripts.walk_revisions())


def verify_upgrade_and_restart(engine, monkeypatch):
    before = set(sa.inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO departments (code,name) VALUES ('RB-SENTINEL','Preserve active runtime data')"))
    cold_start(monkeypatch)
    assert set(sa.inspect(engine).get_table_names()) == before  # startup performs no DDL
    command.upgrade(config(), "head")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_heads() == (SUCCESSOR,)
    assert set(sa.inspect(engine).get_table_names()) - before == set(ECO_COLUMNS)
    cold_start(monkeypatch)
    cold_start(monkeypatch)  # actual lifespan startup repeats against the same upgraded DB
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT name FROM departments WHERE code='RB-SENTINEL'")).scalar_one() == "Preserve active runtime data"
    assert not any(route.path.startswith(("/api/eco-inventory", "/api/eco-accessories")) for route in main.app.routes)


def test_active_predecessor_upgrade_and_cold_restart(rollback_engine, monkeypatch):
    verify_upgrade_and_restart(rollback_engine, monkeypatch)


@pytest.mark.parametrize("table", sorted(ECO_COLUMNS))
def test_predecessor_with_any_partial_eco_table_refuses_startup(rollback_engine, monkeypatch, table):
    with rollback_engine.begin() as connection:
        connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    with pytest.raises(RuntimeError, match="partial/unversioned"):
        cold_start(monkeypatch)


@pytest.mark.parametrize("head", ["0149_besttex_cutting_access", "0151_eco_accessory_approval", "unknown_future_head"])
def test_unknown_or_unmerged_head_refuses_startup(rollback_engine, monkeypatch, head):
    with rollback_engine.begin() as connection:
        connection.execute(sa.text("UPDATE alembic_version SET version_num = :head"), {"head": head})
    with pytest.raises(RuntimeError, match="required Alembic head"):
        cold_start(monkeypatch)


def test_successor_missing_table_or_details_refuses_startup(rollback_engine, monkeypatch):
    command.upgrade(config(), "head")
    with rollback_engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE eco_material_batches DROP COLUMN receipt_details")
    with pytest.raises(RuntimeError, match="incomplete"):
        cold_start(monkeypatch)


def test_successor_claim_without_tables_refuses_startup(rollback_engine, monkeypatch):
    with rollback_engine.begin() as connection:
        connection.execute(sa.text("UPDATE alembic_version SET version_num = :head"), {"head": SUCCESSOR})
    with pytest.raises(RuntimeError, match="incomplete"):
        cold_start(monkeypatch)


def test_upgraded_rollback_freezes_eco_only_and_preserves_item_evidence(rollback_engine):
    from app.libs.dto.inventory.item_input import ItemIn
    from app.models.inventory import stock_service
    from app.models.inventory_service import ensure_accessories_issued_for_sewing
    from app.schemas import Department, Item, Model, ProductionOrder, Role, User, WorkOrder

    with Session(rollback_engine, expire_on_commit=False) as db:
        role = Role(name="Super Admin", permissions=["*"])
        user = User(email="rollback@disposable.invalid", name="Rollback test", password_hash="unused", role=role)
        item = Item(sku="ROLLBACK-ITEM", name="Rollback stock", category="fabric", unit="kg")
        model = Model(code="ROLLBACK-MODEL", name="Rollback model")
        eco = Department(code="ECO", name="Eco")
        mil = Department(code="MIL", name="Milana")
        db.add_all([user, item, model, eco, mil]); db.flush()
        order = ProductionOrder(production_no="PO-ROLLBACK", production_type="branded_stock", model_id=model.id)
        db.add(order); db.flush()
        eco_work = WorkOrder(production_order_id=order.id, department_id=eco.id, operation="sewing")
        mil_work = WorkOrder(production_order_id=order.id, department_id=mil.id, operation="sewing")
        db.add_all([eco_work, mil_work]); db.commit()
        # Exact old schema retains its old gate, even for ECO.
        assert ensure_accessories_issued_for_sewing(db, order.id, sewing_factory_code="ECO")["is_complete"]
        db.rollback()
        command.upgrade(config(), "head")
        for kwargs in ({"sewing_factory_code": "ECO"}, {"sewing_work_order_id": eco_work.id}, {}):
            with pytest.raises(HTTPException, match="compatibility rollback"):
                ensure_accessories_issued_for_sewing(db, order.id, **kwargs)
            db.rollback()
        assert ensure_accessories_issued_for_sewing(db, order.id, sewing_factory_code="MIL")["is_complete"]
        assert ensure_accessories_issued_for_sewing(db, order.id, sewing_factory_code="BST")["is_complete"]
        assert ensure_accessories_issued_for_sewing(db, order.id, sewing_work_order_id=mil_work.id)["is_complete"]
        db.execute(sa.text("""INSERT INTO eco_material_batches
            (item_id,kind,batch_no,unit,quantity,reserved_quantity,created_by,receipt_details)
            VALUES (:item,'fabric','ECO-ROLLBACK','kg',12,3,:user,'{}')"""), {"item": item.id, "user": user.id})
        db.commit()
        with pytest.raises(HTTPException, match="unit/category"):
            stock_service.update_item(db, item.id, ItemIn(sku=item.sku, name=item.name, category="fabric", unit="m"), user)
        db.rollback()
        with pytest.raises(HTTPException, match="linked"):
            stock_service.delete_item(db, item.id, user)
        db.rollback()
        assert stock_service.delete_item(db, item.id, user, force=True) is True  # archive, never erase evidence
        assert db.execute(sa.text("SELECT quantity,reserved_quantity FROM eco_material_batches")).one() == (12, 3)
        assert db.get(Item, item.id).unit == "kg"


@pytest.mark.parametrize("factory,by_name", [("ECO", False), ("ECO", True), ("MIL", False), ("BST", False)])
def test_record_gate_uses_validated_assignment_factory_on_shared_work(rollback_engine, factory, by_name):
    from app.api.routes.production import post_sewing
    from app.libs.dto.production.production import SewingRecordIn
    from app.schemas import CuttingRecord, Department, Model, ProductionOrder, Role, SewingAssignment, SewingFlow, SewingRecord, User, WorkOrder

    command.upgrade(config(), "head")
    with Session(rollback_engine, expire_on_commit=False) as db:
        role = Role(name="Super Admin", permissions=["*"])
        user = User(email="assignment@disposable.invalid", name="Assignment gate", password_hash="unused", role=role)
        model = Model(code="ASSIGNMENT-MODEL", name="Assignment test")
        dept = Department(code="SEW", name="Shared sewing")
        cut = Department(code="CUT", name="Cutting")
        flow = SewingFlow(factory_code=factory, code="RB-LINE", name="Rollback line")
        db.add_all([user, model, dept, cut, flow]); db.flush()
        order = ProductionOrder(production_no="PO-ASSIGNMENT", production_type="branded_stock", model_id=model.id, planned_quantity=10)
        db.add(order); db.flush()
        work = WorkOrder(production_order_id=order.id, department_id=dept.id, operation="sewing", status="in_progress",
            planned_input_qty=10, planned_output_qty=10)
        cutting = WorkOrder(production_order_id=order.id, department_id=cut.id, operation="cutting", status="in_progress",
            planned_output_qty=10, actual_output_qty=10, passed_qty=10)
        db.add_all([work, cutting]); db.flush()
        assignment = SewingAssignment(work_order_id=work.id, sewing_flow_id=flow.id, quantity=10)
        db.add_all([assignment, CuttingRecord(work_order_id=cutting.id, input_quantity=1, input_unit="kg", cut_pieces=10, passed_pieces=10)])
        db.commit()
        payload = SewingRecordIn(work_order_id=work.id, input_qty=1, sewn_qty=1, passed_qty=1,
            sewing_assignment_id=None if by_name else assignment.id, line_name=flow.code if by_name else None)
        if factory == "ECO":
            with pytest.raises(HTTPException, match="compatibility rollback"):
                post_sewing(payload, db, user)
            db.rollback()
            assert db.query(SewingRecord).count() == 0
            assert assignment.completed_qty == 0
        else:
            result = post_sewing(payload, db, user)
            assert db.get(SewingRecord, result["id"]).passed_qty == 1


def job_owned_pg_url(raw):
    url = make_url(raw)
    if (url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.query or not (url.database or "").endswith(("_ci", "_qa"))):
        pytest.fail("ECO rollback gates require an explicitly disposable loopback *_ci or *_qa database with no URL query")
    return url


@pytest.mark.parametrize("raw", [
    "postgresql://postgres@127.0.0.1/erp",
    "postgresql://postgres@172.16.10.3/review_ci",
    "postgresql://postgres@127.0.0.1/review_ci?hostaddr=172.16.10.3",
    "postgresql://postgres@127.0.0.1/review_ci?options=-csearch_path%3Dpublic",
    "sqlite:///review_ci",
])
def test_postgres_gate_rejects_unsafe_target_before_connect(raw):
    with pytest.raises(pytest.fail.Exception, match="disposable loopback"):
        job_owned_pg_url(raw)


def test_eco_rollback_postgres_migration_and_cold_restart(monkeypatch):
    raw = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw:
        pytest.skip("STABILIZATION_POSTGRES_URL is required for the real PostgreSQL gate")
    url = job_owned_pg_url(raw)
    schema = "eco_rollback_" + uuid4().hex
    admin = sa.create_engine(url)
    engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    created = False
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        created = True
        prepare(engine, monkeypatch, migrate_predecessor=True)
        verify_upgrade_and_restart(engine, monkeypatch)
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE alembic_version SET version_num='unknown_future_head'"))
        with pytest.raises(RuntimeError, match="required Alembic head"):
            cold_start(monkeypatch)
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE alembic_version SET version_num=:head"), {"head": SUCCESSOR})
            connection.exec_driver_sql("ALTER TABLE eco_material_batches DROP COLUMN receipt_details")
        with pytest.raises(RuntimeError, match="incomplete"):
            cold_start(monkeypatch)
    finally:
        engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        admin.dispose()
