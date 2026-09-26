"""Synthetic PostgreSQL rehearsal for the 0090 assignment preview."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.migrations.preflight_0090 import read_only_preflight_0090


POSTGRES_URL = os.environ.get("STABILIZATION_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="disposable PostgreSQL URL required")
BACKEND = Path(__file__).resolve().parents[2]


def _seed(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    sa.Table("alembic_version", metadata, sa.Column("version_num", sa.String, primary_key=True))
    departments = sa.Table("departments", metadata,
                           sa.Column("id", sa.Integer, primary_key=True), sa.Column("code", sa.String))
    users = sa.Table("users", metadata,
                     sa.Column("id", sa.Integer, primary_key=True), sa.Column("department_id", sa.Integer))
    metadata.create_all(connection)
    connection.execute(sa.text(
        "INSERT INTO alembic_version (version_num) VALUES ('0089_packaging_departments')"
    ))
    connection.execute(departments.insert(), [
        {"id": 1, "code": "BST"}, {"id": 2, "code": "ECO"}, {"id": 3, "code": "OTHER"},
    ])
    connection.execute(users.insert(), [
        {"id": 1, "department_id": 1}, {"id": 2, "department_id": 2},
        {"id": 3, "department_id": 3}, {"id": 4, "department_id": None},
    ])


def _upgrade(connection: sa.Connection) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    migration = ScriptDirectory.from_config(config).get_revision("0090_user_factory_access").module
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


@pytest.fixture
def postgres_engine():
    parsed = sa.engine.make_url(POSTGRES_URL)
    if parsed.host != "127.0.0.1" or parsed.username != "erp_test":
        pytest.skip("0090 rehearsal requires disposable local erp_test cluster")
    schema = f"preflight_0090_{uuid4().hex[:12]}"
    admin = sa.create_engine(POSTGRES_URL, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(POSTGRES_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_0090_preflight_matches_synthetic_postgres_upgrade(postgres_engine):
    with postgres_engine.begin() as connection:
        _seed(connection)
    report = read_only_preflight_0090(postgres_engine)
    assert report["migration_pending"] is True
    assert report["implicit_mil_fallback_count"] == 2
    with postgres_engine.begin() as connection:
        _upgrade(connection)
    with postgres_engine.connect() as connection:
        table = sa.Table("users", sa.MetaData(), autoload_with=connection)
        actual = connection.execute(sa.select(table.c.id, table.c.factory_code).order_by(table.c.id)).all()
        assert actual == [(row["user_id"], row["after"]["factory_code"]) for row in report["users"]]
