import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_payroll_sewing_grants_preserve_existing_access(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0126_payroll_sewing_access.py"
    spec = importlib.util.spec_from_file_location("payroll_sewing_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    roles = sa.Table("roles", metadata, sa.Column("id", sa.Integer, primary_key=True),
                     sa.Column("name", sa.String), sa.Column("permissions", sa.JSON))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(roles.insert(), [
            {"id": 1, "name": "Payroll", "permissions": ["payroll.view", "custom.permission", "sewing.flows"]},
            {"id": 2, "name": "Planning", "permissions": ["planning.production"]},
            {"id": 3, "name": "PAYROLL", "permissions": None},
        ])
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        first = dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all())
        assert first[1] == ["payroll.view", "custom.permission", "sewing.flows", "sewing.records", "sewing.bundles"]
        assert first[2] == ["planning.production"]
        assert first[3] == ["sewing.flows", "sewing.records", "sewing.bundles"]
        migration.upgrade()
        assert dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all()) == first
        migration.downgrade()
        assert dict(connection.execute(sa.select(roles.c.id, roles.c.permissions)).all()) == first
