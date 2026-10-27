"""Existing rows survive the optional pack-order and dispatch snapshot migration."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_pack_sales_dispatch_migration_preserves_history_and_evidence():
    path = Path(__file__).parents[2] / "alembic/versions/0116_pack_sales_dispatch.py"
    spec = importlib.util.spec_from_file_location("pack_sales_dispatch_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE sales_order_items (id INTEGER PRIMARY KEY, quantity INTEGER NOT NULL)"))
        connection.execute(sa.text("CREATE TABLE shipments (id INTEGER PRIMARY KEY, status TEXT NOT NULL)"))
        connection.execute(sa.text("INSERT INTO sales_order_items VALUES (1, 17)"))
        connection.execute(sa.text("INSERT INTO shipments VALUES (1, 'delivered')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert tuple(connection.execute(sa.text("SELECT quantity, requested_pack_count FROM sales_order_items")).one()) == (17, None)
            assert tuple(connection.execute(sa.text("SELECT status, dispatch_snapshot FROM shipments")).one()) == ("delivered", None)
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("UPDATE sales_order_items SET requested_pack_count=0"))
            connection.execute(sa.text("UPDATE sales_order_items SET requested_pack_count=2"))
            with pytest.raises(RuntimeError, match="requested physical pack"):
                migration.downgrade()
            connection.execute(sa.text("UPDATE sales_order_items SET requested_pack_count=NULL"))
            connection.execute(sa.text("UPDATE shipments SET dispatch_snapshot='{}'"))
            with pytest.raises(RuntimeError, match="shipment invoice snapshots"):
                migration.downgrade()
            connection.execute(sa.text("UPDATE shipments SET dispatch_snapshot=NULL"))
            migration.downgrade()
            assert [column["name"] for column in sa.inspect(connection).get_columns("sales_order_items")] == ["id", "quantity"]
            assert [column["name"] for column in sa.inspect(connection).get_columns("shipments")] == ["id", "status"]
            assert connection.execute(sa.text("SELECT quantity FROM sales_order_items")).scalar() == 17
    engine.dispose()
