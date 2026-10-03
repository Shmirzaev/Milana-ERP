"""DB08: the sales/Beyka ORM must agree with the shipped migration schema.

Revision ``0071_model_less_legacy_sales`` is already shipped and has already run
against the migrated clone database, so it is the schema source of truth. It made
``sales_order_items.model_id`` nullable and added the model-less legacy stock
columns. This module proves the ORM still disagreed with that, and now agrees.

Two layers, deliberately:

* ``test_sales_item_orm_declares_model_less_legacy_contract`` needs no database
  and encodes 0071's declared contract directly, so it can never pass by
  skipping.
* ``test_migrated_postgres_sales_tables_match_orm`` reflects the tables produced
  by the real Alembic chain on a real PostgreSQL and compares them to the ORM
  column by column. ``STABILIZATION_POSTGRES_URL`` is unset by default and this
  test then SKIPS; it is never counted as passing coverage.
"""

import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 0071_model_less_legacy_sales.upgrade() -- shipped, already applied.
LEGACY_STOCK_COLUMN = ("finished_goods_stock_id", "INTEGER", True)
SOURCE_MODEL_COLUMNS = (
    ("source_model_code", "VARCHAR(64)", True),
    ("source_model_name", "VARCHAR(255)", True),
)


def _sales_tables():
    from app.db.base import Base
    import app.models  # noqa: F401 - register ORM metadata

    return {
        name: Base.metadata.tables[name]
        for name in ("sales_orders", "sales_order_items")
    }


def _check_constraint_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }


def _fk_constraint_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint)
    }


def _orm_foreign_keys(table):
    """(constrained columns) -> (referred table, referred columns) for the ORM."""
    return {
        (tuple(element.parent.name for element in constraint.elements),
         (constraint.elements[0].column.table.name, constraint.elements[0].column.name))
        for constraint in table.constraints
        if isinstance(constraint, sa.ForeignKeyConstraint) and len(constraint.elements) == 1
    }


def _canonical_type(column_type):
    """Dialect-independent type text.

    SQLAlchemy renders the ORM's ``DateTime(timezone=True)`` as ``DATETIME``
    while PostgreSQL reflects the very same column as ``TIMESTAMP``; that is a
    representation difference, not a schema one.
    """
    return str(column_type).upper().replace("DATETIME", "TIMESTAMP")


def test_sales_item_orm_declares_model_less_legacy_contract():
    """No database needed: the ORM must carry all of 0071's shape."""
    table = _sales_tables()["sales_order_items"]

    # 0071 made model_id nullable so a line can reference legacy stock directly.
    assert table.c.model_id.nullable is True, (
        "0071_model_less_legacy_sales sets sales_order_items.model_id nullable=True; "
        "the ORM still declared it NOT NULL"
    )

    # 0071 added the model-less legacy reference columns.
    for name, type_text, nullable in (LEGACY_STOCK_COLUMN, *SOURCE_MODEL_COLUMNS):
        assert name in table.c, f"0071 adds sales_order_items.{name}; ORM has no such column"
        assert str(table.c[name].type) == type_text, (
            f"sales_order_items.{name} type drifted from migration ({type_text})"
        )
        assert table.c[name].nullable is nullable, (
            f"sales_order_items.{name} nullability drifted from migration"
        )

    # 0071 created the named FK, the index and the product-reference CHECK.
    assert "fk_sales_order_items_finished_goods_stock_id" in _fk_constraint_names(table), (
        "0071 creates fk_sales_order_items_finished_goods_stock_id; ORM has no such FK"
    )
    assert "ix_sales_order_items_finished_goods_stock_id" in {
        index.name for index in table.indexes
    }, "0071 creates ix_sales_order_items_finished_goods_stock_id; ORM has no such index"
    assert "ck_sales_order_items_product_reference" in _check_constraint_names(table), (
        "0071 creates ck_sales_order_items_product_reference; ORM has no such CHECK"
    )


@pytest.fixture
def migrated_postgres(monkeypatch):
    """Disposable loopback PostgreSQL schema built by the real migration chain.

    Mirrors the DB04 harness: the suite runner supplies STABILIZATION_POSTGRES_URL,
    every test owns and drops its own schema, and the application fixture keeps
    using SQLite. env.py does not accept an injected connection, so Alembic's
    engine factory is routed at the disposable schema instead.
    """
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for disposable PostgreSQL migration coverage")
    url = sa.engine.make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Migration tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"db08_sales_orm_{uuid4().hex}"
    engine = sa.create_engine(
        url, poolclass=sa.pool.NullPool,
        connect_args={"options": f"-csearch_path={schema} -cstatement_timeout=60000"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        from app.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", url.render_as_string(hide_password=False))
        monkeypatch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
        yield SimpleNamespace(engine=engine, config=Config(os.path.join(BACKEND, "alembic.ini")))
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def test_migrated_postgres_sales_tables_match_orm(migrated_postgres):
    """Reflect the real migrated schema and compare it to the ORM, column by column.

    This is the only assertion in this module that proves ORM/database parity.
    It requires a genuine Alembic-upgraded PostgreSQL; a ``create_all`` database
    is not a substitute and is never used here.
    """
    engine, config = migrated_postgres.engine, migrated_postgres.config
    command.upgrade(config, "head")

    tables = _sales_tables()
    mismatches = []
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for name, orm_table in tables.items():
            migrated_columns = {column["name"]: column for column in inspector.get_columns(name)}
            for column_name, orm_column in orm_table.columns.items():
                if column_name not in migrated_columns:
                    mismatches.append(f"{name}.{column_name}: ORM column absent from migrated schema")
                    continue
                migrated = migrated_columns[column_name]
                if migrated["nullable"] != orm_column.nullable:
                    mismatches.append(
                        f"{name}.{column_name}: nullability ORM={orm_column.nullable} "
                        f"migrated={migrated['nullable']}"
                    )
                if _canonical_type(migrated["type"]) != _canonical_type(orm_column.type):
                    mismatches.append(
                        f"{name}.{column_name}: type ORM={orm_column.type} migrated={migrated['type']}"
                    )
            for column_name in migrated_columns:
                if column_name not in orm_table.columns:
                    mismatches.append(f"{name}.{column_name}: migrated column absent from ORM")

            # Compare foreign keys by what they actually do (columns -> target),
            # not by constraint name: PostgreSQL auto-names every unnamed FK
            # <table>_<column>_fkey, so names are only comparable when a
            # migration set one explicitly. The explicit 0071 FK name is asserted
            # by test_sales_item_orm_declares_model_less_legacy_contract.
            for key in {
                (tuple(fk["constrained_columns"]), tuple([fk["referred_table"], *fk["referred_columns"]]))
                for fk in inspector.get_foreign_keys(name)
            } - _orm_foreign_keys(orm_table):
                mismatches.append(f"{name}: migrated FK {key} absent from ORM")

            migrated_indexes = {index["name"] for index in inspector.get_indexes(name)}
            for index_name in migrated_indexes - {index.name for index in orm_table.indexes}:
                mismatches.append(f"{name}: migrated index {index_name} absent from ORM")

    assert mismatches == [], (
        "sales/Beyka ORM metadata disagrees with the migrated schema: " + "; ".join(mismatches)
    )


def test_migrated_postgres_enforces_model_less_legacy_check(migrated_postgres):
    """The migrated CHECK must exist, and the ORM must declare the same name.

    Alembic autogenerate does not compare CHECK constraints, so the drift
    baseline cannot catch this one; it is asserted explicitly instead.
    """
    engine, config = migrated_postgres.engine, migrated_postgres.config
    command.upgrade(config, "head")

    with engine.connect() as connection:
        migrated_checks = {
            check["name"] for check in sa.inspect(connection).get_check_constraints("sales_order_items")
        }
    assert "ck_sales_order_items_product_reference" in migrated_checks, (
        "0071 must have created ck_sales_order_items_product_reference on the migrated schema"
    )
    assert "ck_sales_order_items_product_reference" in _check_constraint_names(
        _sales_tables()["sales_order_items"]
    ), "ORM does not declare the migrated product-reference CHECK"

    # A line with neither a model nor legacy stock must be refused by the real DB.
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO models (code, name, status, sam_minutes) "
            "VALUES ('DB08-C', 'db08', 'draft', 0)"
        )
        connection.exec_driver_sql(
            "INSERT INTO sales_orders (order_no, order_type, status, total_amount) "
            "VALUES ('DB08-ORD', 'client_order', 'draft', 0)"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO sales_order_items (sales_order_id, color, size, quantity, unit_price, "
                "printing_required, source_type) VALUES "
                "((SELECT id FROM sales_orders WHERE order_no = 'DB08-ORD'), 'c', 'm', 1, 1, false, 'produce_new')"
            )
