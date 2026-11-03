"""Execute both new migrations against a disposable predecessor schema."""
import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from app.db.base import Base

NEW_TABLES = {"eco_material_batches", "eco_material_movements", "factory_fabric_transfers", "factory_fabric_transfer_lines",
              "eco_accessory_plans", "eco_accessory_requirements", "eco_accessory_allocations"}


def migration(name):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_new_upgrade_shapes_and_safe_empty_downgrade():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name not in NEW_TABLES])
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            stock = migration("0150_eco_inventory_transfers.py")
            approval = migration("0151_eco_accessory_approval.py")
            stock.upgrade(); approval.upgrade()
            actual = inspect(connection)
            for name in NEW_TABLES:
                assert {c["name"] for c in actual.get_columns(name)} == set(Base.metadata.tables[name].columns.keys())
            approval.downgrade(); stock.downgrade()
            assert not NEW_TABLES.intersection(inspect(connection).get_table_names())
    engine.dispose()


def test_downgrade_refuses_to_erase_approval_evidence():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO eco_accessory_plans (production_order_id, model_id, planning_order_id, planned_quantity, status, revision, notes, created_by) VALUES (1,1,1,10,'draft',1,'',1)"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="history exists"):
                migration("0151_eco_accessory_approval.py").downgrade()
        assert connection.execute(text("SELECT count(*) FROM eco_accessory_plans")).scalar() == 1
    engine.dispose()
