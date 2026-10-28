import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_storage_customers_grants_preserve_existing_access(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0133_storage_customers.py"
    spec = importlib.util.spec_from_file_location("storage_customers_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    roles = sa.Table("roles", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("name", sa.String), sa.Column("permissions", sa.JSON))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(roles.insert(), [
            {"id": 1, "name": "Storage", "permissions": ["storage.shipment", "custom.permission", "sales.customers"]},
            {"id": 2, "name": "Planning", "permissions": ["planning.production"]},
            {"id": 3, "name": "ReadyStorage", "permissions": None},
        ])
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        first = dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all())
        assert first[1] == ["storage.shipment", "custom.permission", "sales.customers"]
        assert first[2] == ["planning.production"]
        assert first[3] == ["sales.customers"]
        migration.upgrade()
        assert dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all()) == first
        migration.downgrade()
        assert dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all()) == first
