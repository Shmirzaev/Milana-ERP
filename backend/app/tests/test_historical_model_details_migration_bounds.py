"""Historical revisions must accept JSON saved before today's write limits."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

from app.tests.test_fresh_migration_bootstrap import postgres_migrations  # noqa: F401


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _revision(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_details() -> dict:
    # A single model can have hundreds of paid operations. 0086 triples them.
    operations = [{"id": f"operation-{index}", "name": f"Sewing {index} " + "x" * 100}
                  for index in range(400)]
    nested = {"leaf": True}
    for _ in range(20):
        nested = {"next": nested}
    details = {
        "general": {"variant_stock_batch_id": 7, "variant_no": "V-1"},
        "paidOperations": operations,
        "legacy_extension": "y" * 20_000,
        "legacy_nested": nested,
    }
    assert len(json.dumps(details).encode("utf-8")) > 64 * 1024
    return details


def test_0062_moves_fabric_identity_without_rejecting_large_legacy_details() -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    original = _legacy_details()
    frozen = deepcopy(original)

    result = migration._updated_model_details(
        original, {"item_id": 9, "name": "Cotton", "sku": "F-9"},
    )

    assert result is not None
    assert result["general"] == {
        "variant_no": "V-1", "variant_fabric_item_id": 9, "variant_fabric": "Cotton (F-9)",
    }
    assert result["paidOperations"] == original["paidOperations"]
    assert result["legacy_extension"] == original["legacy_extension"]
    assert result["legacy_nested"] == original["legacy_nested"]
    assert original == frozen


def test_0062_skips_unchanged_large_legacy_details() -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    original = {"legacy_extension": "x" * (70 * 1024)}

    assert migration._updated_model_details(original, None) is None


def test_0086_expands_and_collapses_large_legacy_operations_losslessly() -> None:
    migration = _revision("0086_paid_operation_factories.py")
    original = _legacy_details()
    frozen = deepcopy(original)

    expanded = migration._expand_details(original)

    assert expanded is not None
    assert len(expanded["paid_operations"]) == 3 * len(original["paidOperations"])
    assert {row["sewingFactory"] for row in expanded["paid_operations"]} == set(migration.FACTORIES)
    assert len(json.dumps(expanded).encode("utf-8")) > 64 * 1024
    assert expanded["general"] == original["general"]
    assert expanded["legacy_extension"] == original["legacy_extension"]
    assert expanded["legacy_nested"] == original["legacy_nested"]
    assert original == frozen
    assert migration._collapse_details(expanded) == {
        "general": original["general"],
        "paid_operations": original["paidOperations"],
        "legacy_extension": original["legacy_extension"],
        "legacy_nested": original["legacy_nested"],
    }


def test_0086_skips_already_scoped_large_legacy_details() -> None:
    migration = _revision("0086_paid_operation_factories.py")
    original = {"paid_operations": [{"id": "current", "sewingFactory": "milana"}],
                "legacy_extension": "x" * (70 * 1024)}

    assert migration._expand_details(original) is None


def test_postgres_historical_revisions_preserve_large_legacy_json(postgres_migrations) -> None:
    migration_0062 = _revision("0062_planning_fabric_batch.py")
    migration_0086 = _revision("0086_paid_operation_factories.py")
    metadata = sa.MetaData()
    models = sa.Table("models", metadata,
                      sa.Column("id", sa.Integer, primary_key=True), sa.Column("details_json", sa.JSON))
    items = sa.Table("items", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("name", sa.String), sa.Column("sku", sa.String),
                     sa.Column("category", sa.String), sa.Column("image_url", sa.String))
    sa.Table("stock_batches", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("production_orders", metadata, sa.Column("id", sa.Integer, primary_key=True))
    model_bom = sa.Table("model_bom", metadata, sa.Column("id", sa.Integer, primary_key=True),
                         sa.Column("model_id", sa.Integer), sa.Column("item_id", sa.Integer),
                         sa.Column("stock_batch_id", sa.Integer), sa.Column("photo_url", sa.String))
    original = _legacy_details()

    with postgres_migrations.engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(models.insert().values(id=1, details_json=original))
        connection.execute(items.insert().values(id=9, name="Cotton", sku="F-9",
                                                 category="fabric", image_url="/cotton.jpg"))
        connection.execute(model_bom.insert().values(id=1, model_id=1, item_id=9, stock_batch_id=7))

        with Operations.context(MigrationContext.configure(connection)):
            migration_0062.upgrade()
            after_0062 = connection.execute(sa.select(models.c.details_json)).scalar_one()
            assert after_0062["general"]["variant_fabric_item_id"] == 9
            assert after_0062["paidOperations"] == original["paidOperations"]
            migration_0086.upgrade()
            expanded = connection.execute(sa.select(models.c.details_json)).scalar_one()
            assert len(expanded["paid_operations"]) == 1200
            assert expanded["legacy_extension"] == original["legacy_extension"]
            assert expanded["legacy_nested"] == original["legacy_nested"]
            migration_0086.downgrade()
            restored = connection.execute(sa.select(models.c.details_json)).scalar_one()
            assert restored["paid_operations"] == original["paidOperations"]
            assert restored["general"] == after_0062["general"]
            assert restored["legacy_extension"] == original["legacy_extension"]
            assert restored["legacy_nested"] == original["legacy_nested"]

        bom = connection.execute(sa.select(model_bom.c.stock_batch_id, model_bom.c.photo_url)).one()
        assert bom == (None, "/cotton.jpg")
