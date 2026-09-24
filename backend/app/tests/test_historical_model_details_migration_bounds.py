from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _revision(filename: str):
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deep_extension() -> dict:
    nested: dict = {"leaf": True}
    for _ in range(20):
        nested = {"next": nested}
    return nested


@pytest.mark.parametrize("invalid", ["oversized", "deep"])
def test_0062_rejects_changed_unbounded_details_without_mutating_source(invalid: str) -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    extension = "x" * (70 * 1024) if invalid == "oversized" else _deep_extension()
    original = {"general": {"variant_stock_batch_id": 7}, "legacy_extension": extension}
    frozen = deepcopy(original)

    with pytest.raises(ValueError, match="details_json cannot exceed"):
        migration._updated_model_details(original, None, model_id=42)

    assert original == frozen


def test_0062_skips_unchanged_oversized_details() -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    original = {"legacy_extension": "x" * (70 * 1024)}

    assert migration._updated_model_details(original, None, model_id=42) is None


def test_0062_preserves_legacy_fields_when_moving_fabric_identity() -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    original = {"general": {"variant_stock_batch_id": 7, "variant_no": "V-1"}, "legacy_extension": True}

    result = migration._updated_model_details(
        original, {"item_id": 9, "name": "Cotton", "sku": "F-9"}, model_id=42,
    )

    assert result == {
        "general": {"variant_no": "V-1", "variant_fabric_item_id": 9, "variant_fabric": "Cotton (F-9)"},
        "legacy_extension": True,
    }
    assert original["general"]["variant_stock_batch_id"] == 7


@pytest.mark.parametrize("invalid", ["oversized", "deep"])
def test_0086_rejects_expanded_unbounded_details_without_mutating_source(invalid: str) -> None:
    migration = _revision("0086_paid_operation_factories.py")
    extension = "x" * (70 * 1024) if invalid == "oversized" else _deep_extension()
    original = {"paid_operations": [{"id": "legacy", "name": "Sewing"}], "legacy_extension": extension}
    frozen = deepcopy(original)

    with pytest.raises(ValueError, match="details_json cannot exceed"):
        migration._expand_details(original, model_id=42)

    assert original == frozen


def test_0086_skips_unchanged_oversized_details() -> None:
    migration = _revision("0086_paid_operation_factories.py")
    original = {"paid_operations": [{"id": "current", "sewingFactory": "milana"}], "legacy_extension": "x" * (70 * 1024)}

    assert migration._expand_details(original, model_id=42) is None


def test_0086_expands_and_collapses_legacy_operations_with_other_fields_intact() -> None:
    migration = _revision("0086_paid_operation_factories.py")
    original = {"paidOperations": [{"id": "sew", "name": "Sewing"}], "legacy_extension": {"keep": True}}

    expanded = migration._expand_details(original, model_id=42)

    assert expanded is not None
    assert {row["sewingFactory"] for row in expanded["paid_operations"]} == set(migration.FACTORIES)
    assert expanded["legacy_extension"] == original["legacy_extension"]
    assert original["paidOperations"] == [{"id": "sew", "name": "Sewing"}]
    assert migration._collapse_details(expanded, model_id=42) == {
        "paid_operations": [{"id": "sew", "name": "Sewing"}],
        "legacy_extension": {"keep": True},
    }


def test_0086_later_unbounded_row_rolls_back_earlier_rewrite(monkeypatch) -> None:
    migration = _revision("0086_paid_operation_factories.py")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    models = sa.Table(
        "models", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("details_json", sa.JSON),
    )
    metadata.create_all(engine)
    first = {"paid_operations": [{"id": "first"}]}
    second = {"paid_operations": [{"id": "second"}], "extension": "x" * (70 * 1024)}
    with engine.begin() as db:
        db.execute(models.insert(), [{"id": 1, "details_json": first}, {"id": 2, "details_json": second}])

    with pytest.raises(ValueError, match="Model 2 details_json cannot exceed"):
        with engine.begin() as db:
            monkeypatch.setattr(migration.op, "get_bind", lambda: db)
            migration.upgrade()

    with engine.connect() as db:
        assert db.execute(sa.select(models.c.details_json).order_by(models.c.id)).scalars().all() == [first, second]


def test_0062_later_unbounded_row_rolls_back_earlier_rewrite(monkeypatch) -> None:
    migration = _revision("0062_planning_fabric_batch.py")
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    models = sa.Table(
        "models", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("details_json", sa.JSON),
    )
    sa.Table(
        "model_bom", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("model_id", sa.Integer),
        sa.Column("item_id", sa.Integer),
        sa.Column("stock_batch_id", sa.Integer),
        sa.Column("photo_url", sa.String),
    )
    sa.Table(
        "items", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("sku", sa.String),
        sa.Column("category", sa.String),
        sa.Column("image_url", sa.String),
    )
    metadata.create_all(engine)
    first = {"general": {"variant_stock_batch_id": 7}}
    second = {"general": {"variant_stock_batch_id": 8}, "extension": "x" * (70 * 1024)}
    with engine.begin() as db:
        db.execute(models.insert(), [{"id": 1, "details_json": first}, {"id": 2, "details_json": second}])

    monkeypatch.setattr(migration.op, "add_column", lambda *args: None)
    monkeypatch.setattr(migration.op, "create_foreign_key", lambda *args: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args: None)
    with pytest.raises(ValueError, match="Model 2 details_json cannot exceed"):
        with engine.begin() as db:
            monkeypatch.setattr(migration.op, "get_bind", lambda: db)
            migration.upgrade()

    with engine.connect() as db:
        assert db.execute(sa.select(models.c.details_json).order_by(models.c.id)).scalars().all() == [first, second]
