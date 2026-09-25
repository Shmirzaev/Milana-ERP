"""Rehearse the 0101 preflight against its real PostgreSQL migration."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from alembic.config import Config

from app.migrations.preflight_0101 import read_only_preflight_0101


POSTGRES_URL = os.environ.get("STABILIZATION_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="disposable PostgreSQL URL required")
BACKEND = Path(__file__).resolve().parents[2]


def _predecessor_schema(connection: sa.Connection, *, mixed_period: bool) -> None:
    metadata = sa.MetaData()
    sa.Table("alembic_version", metadata, sa.Column("version_num", sa.String, primary_key=True))
    users = sa.Table(
        "users", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("factory_code", sa.String(3)),
    )
    departments = sa.Table(
        "departments", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String),
    )
    employees = sa.Table(
        "employees", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer), sa.Column("department_id", sa.Integer),
        sa.Column("employee_no", sa.String),
    )
    sa.Index("ix_employees_employee_no", employees.c.employee_no, unique=True)
    periods = sa.Table(
        "payroll_periods", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("period_no", sa.String), sa.Column("created_by", sa.Integer),
    )
    sa.Index("ix_payroll_periods_period_no", periods.c.period_no, unique=True)
    records = sa.Table(
        "payroll_records", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payroll_period_id", sa.Integer), sa.Column("employee_id", sa.Integer),
        sa.Column("scanned_by", sa.Integer), sa.Column("scan_uid", sa.String),
        sa.Column("dedupe_key", sa.String),
        sa.UniqueConstraint("scan_uid", name="uq_payroll_records_scan_uid"),
        sa.UniqueConstraint("dedupe_key", name="uq_payroll_records_dedupe_key"),
    )
    labels = sa.Table(
        "payroll_qr_labels", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("payroll_record_id", sa.Integer), sa.Column("sewing_flow_id", sa.Integer),
        sa.Column("production_order_id", sa.Integer), sa.Column("issued_by", sa.Integer),
        sa.Column("label_uid", sa.String),
        sa.UniqueConstraint("label_uid", name="uq_payroll_qr_labels_label_uid"),
    )
    adjustments = sa.Table(
        "payroll_adjustments", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("employee_id", sa.Integer), sa.Column("created_by", sa.Integer),
    )
    sa.Table(
        "sewing_flows", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("factory_code", sa.String),
    )
    sa.Table(
        "bundles", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("production_order_id", sa.Integer), sa.Column("status", sa.String),
        sa.Column("sewing_factory_code", sa.String),
    )
    metadata.create_all(connection)
    connection.execute(sa.text(
        "INSERT INTO alembic_version (version_num) VALUES ('0100_material_roll_weights')"
    ))
    connection.execute(users.insert(), [
        {"id": 1, "factory_code": "BST"}, {"id": 2, "factory_code": "ECO"},
    ])
    connection.execute(departments.insert(), [
        {"id": 10, "code": "BPK"}, {"id": 11, "code": "ECT"},
    ])
    connection.execute(employees.insert(), [
        {"id": 1, "user_id": 1, "department_id": 10, "employee_no": "BST-1"},
        {"id": 2, "user_id": 2, "department_id": 11, "employee_no": "ECO-1"},
    ])
    connection.execute(periods.insert(), [
        {"id": 1, "period_no": "P-1", "created_by": 1},
        {"id": 2, "period_no": "P-2", "created_by": 2},
    ])
    connection.execute(records.insert(), [
        {"id": 1, "payroll_period_id": 1, "employee_id": 1,
         "scan_uid": "scan-1", "dedupe_key": "dedupe-1"},
        {"id": 2, "payroll_period_id": 1 if mixed_period else 2, "employee_id": 2,
         "scan_uid": "scan-2", "dedupe_key": "dedupe-2"},
    ])
    connection.execute(labels.insert(), [
        {"id": 1, "payroll_record_id": 1, "label_uid": "label-1"},
        {"id": 2, "payroll_record_id": 2, "label_uid": "label-2"},
    ])
    connection.execute(adjustments.insert(), [
        {"id": 1, "employee_id": 1}, {"id": 2, "employee_id": 2},
    ])


def _migration():
    config = Config(str(BACKEND / "alembic.ini"))
    return ScriptDirectory.from_config(config).get_revision("0101_payroll_factory_scope").module


def _upgrade(connection: sa.Connection) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        _migration().upgrade()


@pytest.fixture
def postgres_engine():
    parsed = sa.engine.make_url(POSTGRES_URL)
    if parsed.host != "127.0.0.1" or parsed.username != "erp_test":
        pytest.skip("0101 rehearsal requires the disposable local erp_test cluster")
    schema_name = f"preflight_0101_{uuid4().hex[:12]}"
    admin_engine = sa.create_engine(POSTGRES_URL, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
    engine = sa.create_engine(
        POSTGRES_URL, pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema_name}" CASCADE')
        admin_engine.dispose()


@pytest.mark.parametrize("mixed_period", [False, True])
def test_0101_preflight_matches_postgres_upgrade_or_blocker(postgres_engine, mixed_period):
    with postgres_engine.begin() as connection:
        _predecessor_schema(connection, mixed_period=mixed_period)
    report = read_only_preflight_0101(postgres_engine)
    assert report["migration_pending"] is True
    assert bool(report["blockers"]) is mixed_period

    if mixed_period:
        with pytest.raises(Exception, match="multiple factories"):
            with postgres_engine.begin() as connection:
                _upgrade(connection)
        assert "factory_code" not in {
            column["name"] for column in sa.inspect(postgres_engine).get_columns("payroll_records")
        }
        return

    with postgres_engine.begin() as connection:
        _upgrade(connection)
    with postgres_engine.connect() as connection:
        for table_name, prediction in report["factory_code_predictions"].items():
            table = sa.Table(table_name, sa.MetaData(), autoload_with=connection)
            actual = connection.execute(
                sa.select(table.c.id, table.c.factory_code).order_by(table.c.id)
            ).all()
            expected = [
                (row["id"], row["factory_code_after"]) for row in prediction["predictions"]
            ]
            assert actual == expected
