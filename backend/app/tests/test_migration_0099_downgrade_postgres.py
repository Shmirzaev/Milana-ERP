"""Directly rehearse revision 0099's downgrade on synthetic PostgreSQL schemas."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


POSTGRES_URL = os.environ.get("STABILIZATION_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="disposable PostgreSQL URL required")
BACKEND = Path(__file__).resolve().parents[2]


def _predecessor_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    labels = sa.Table(
        "payroll_qr_labels", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by", sa.Integer),
        sa.Column("split_from_label_id", sa.Integer),
        sa.CheckConstraint(
            "status IN ('available', 'scanned', 'superseded')",
            name="ck_payroll_qr_labels_status",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"], [users.c.id], name="fk_payroll_qr_labels_superseded_by_users",
        ),
        sa.ForeignKeyConstraint(
            ["split_from_label_id"], ["payroll_qr_labels.id"],
            name="fk_payroll_qr_labels_split_from", ondelete="RESTRICT",
        ),
    )
    sa.Index("ix_payroll_qr_labels_split_from_label_id", labels.c.split_from_label_id)
    metadata.create_all(connection)
    connection.execute(users.insert(), [{"id": 1}, {"id": 2}])


def _downgrade(connection: sa.Connection) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    migration = ScriptDirectory.from_config(config).get_revision("0099_payroll_qr_edit_split").module
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()


@pytest.fixture
def postgres_engine():
    parsed = sa.engine.make_url(POSTGRES_URL)
    if parsed.host != "127.0.0.1" or parsed.username not in {"erp_test", "regression"}:
        pytest.skip("0099 downgrade rehearsal requires a disposable local erp_test/regression cluster")
    schema = f"downgrade_0099_{uuid4().hex[:12]}"
    admin = sa.create_engine(POSTGRES_URL, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = sa.create_engine(
        POSTGRES_URL, pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.mark.parametrize("evidence", [
    {"id": 10, "status": "superseded"},
    {"id": 10, "status": "available", "split_from_label_id": 20},
    {"id": 10, "status": "scanned", "superseded_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "superseded_by": 2},
])
def test_0099_postgres_downgrade_refuses_before_ddl_with_evidence(postgres_engine, evidence):
    with postgres_engine.begin() as connection:
        _predecessor_schema(connection)
        labels = sa.Table("payroll_qr_labels", sa.MetaData(), autoload_with=connection)
        if evidence.get("split_from_label_id") is not None:
            connection.execute(labels.insert(), {"id": 20, "status": "available"})
        connection.execute(labels.insert(), evidence)

    with postgres_engine.begin() as connection:
        before_columns = {column["name"] for column in sa.inspect(connection).get_columns("payroll_qr_labels")}
        before_fks = {fk["name"] for fk in sa.inspect(connection).get_foreign_keys("payroll_qr_labels")}
        before_checks = {check["name"] for check in sa.inspect(connection).get_check_constraints("payroll_qr_labels")}
        before_indexes = {index["name"] for index in sa.inspect(connection).get_indexes("payroll_qr_labels")}
        with pytest.raises(RuntimeError, match="Refusing to downgrade 0099"):
            _downgrade(connection)

    with postgres_engine.connect() as connection:
        labels = sa.Table("payroll_qr_labels", sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(labels).order_by(labels.c.id)).mappings().all()
        assert rows
        assert {column["name"] for column in sa.inspect(connection).get_columns("payroll_qr_labels")} == before_columns
        assert {fk["name"] for fk in sa.inspect(connection).get_foreign_keys("payroll_qr_labels")} == before_fks
        assert {check["name"] for check in sa.inspect(connection).get_check_constraints("payroll_qr_labels")} == before_checks
        assert {index["name"] for index in sa.inspect(connection).get_indexes("payroll_qr_labels")} == before_indexes


def test_0099_postgres_downgrade_succeeds_when_no_split_or_supersession_evidence(postgres_engine):
    with postgres_engine.begin() as connection:
        _predecessor_schema(connection)
        labels = sa.Table("payroll_qr_labels", sa.MetaData(), autoload_with=connection)
        connection.execute(labels.insert(), {"id": 1, "status": "available"})
        _downgrade(connection)

    with postgres_engine.connect() as connection:
        labels = sa.Table("payroll_qr_labels", sa.MetaData(), autoload_with=connection)
        assert {column["name"] for column in sa.inspect(connection).get_columns("payroll_qr_labels")} == {
            "id", "status",
        }
        assert connection.execute(sa.select(labels.c.id, labels.c.status)).one() == (1, "available")
        assert not sa.inspect(connection).get_foreign_keys("payroll_qr_labels")
        assert not sa.inspect(connection).get_indexes("payroll_qr_labels")
        status_check = next(
            check for check in sa.inspect(connection).get_check_constraints("payroll_qr_labels")
            if check["name"] == "ck_payroll_qr_labels_status"
        )
        assert "superseded" not in status_check["sqltext"]
