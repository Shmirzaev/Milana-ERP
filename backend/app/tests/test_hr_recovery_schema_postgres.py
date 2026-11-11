"""Fault challenges for the exact, unmapped HR recovery storage contract."""
from dataclasses import replace
import importlib.util

import pytest
import sqlalchemy as sa

from app.db.base import Base
from app.tests import hr_recovery_schema_contract as contract
from app.tests.test_customer_create_postgres import customer_pg_sessions as customer_pg_sessions
from app.tests.test_fresh_migration_bootstrap import _assert_schema_contract_with_known_drift, _known_drift_baseline


def test_hr_recovery_source_and_baseline_are_frozen():
    contract.verify_source_pins()
    assert len(_known_drift_baseline()) == 94
    spec = importlib.util.spec_from_file_location("frozen_hr_index_contract",
        contract.ROOT / "backend/alembic/versions/0156_gate_live_integration.py")
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    metadata = sa.MetaData()
    expected = contract._clone_live_table(frozen.GateLiveJob.__table__, metadata,
        "qa_hr_contract_" + "a" * 32, "public")
    assert {str(index.name) for index in expected.indexes} == {"ix_gate_live_jobs_device_id"}


def test_hr_recovery_refuses_changed_runtime_pin(monkeypatch):
    monkeypatch.setattr(contract, "APP_SHA256", "0" * 64)
    with pytest.raises(AssertionError, match="runtime source changed"):
        contract.verify_source_pins()


@pytest.mark.parametrize("complete", [False, True])
def test_hr_recovery_exception_requires_all_or_no_mappings(monkeypatch, complete):
    metadata = sa.MetaData()
    sa.Table("gate_employee_devices", metadata, sa.Column("id", sa.Integer),
        *([sa.Column("mode", sa.String)] if complete else []))
    for name in contract.LIVE_TABLES if complete else contract.LIVE_TABLES[:1]:
        sa.Table(name, metadata, sa.Column("id", sa.Integer))
    monkeypatch.setattr(Base, "metadata", metadata)
    if complete:
        assert contract.hr_recovery_drift(None) == []
    else:
        with pytest.raises(AssertionError, match="Partial HR recovery mapping"):
            contract.hr_recovery_drift(None)


def _schemas(connection):
    return connection.execute(sa.text("SELECT nspname FROM pg_namespace ORDER BY nspname")).scalars().all()


def test_hr_recovery_exact_contract_and_original_drift_baseline_pass(customer_pg_sessions):
    engine = customer_pg_sessions.kw["bind"]
    with engine.connect() as connection:
        before = _schemas(connection)
        drift = contract.hr_recovery_drift(connection)
        assert len(drift) == 5
        assert {row[1] for row in drift if row[0] == "remove_table"} == set(contract.LIVE_TABLES)
        assert _schemas(connection) == before
    _assert_schema_contract_with_known_drift(engine)
    assert len(_known_drift_baseline()) == 94


FAULTS = {
    "extra_column": "ALTER TABLE gate_live_profiles ADD COLUMN unreviewed TEXT",
    "missing_column": "ALTER TABLE gate_live_profiles DROP COLUMN profile_hash",
    "column_type": "ALTER TABLE gate_live_devices ALTER COLUMN source_host TYPE VARCHAR(512)",
    "nullable": "ALTER TABLE gate_live_jobs ALTER COLUMN request_hash DROP NOT NULL",
    "default": "ALTER TABLE gate_live_devices ALTER COLUMN enabled SET DEFAULT true",
    "timezone": "ALTER TABLE gate_live_profiles ALTER COLUMN observed_at TYPE timestamp without time zone",
    "primary_key": "ALTER TABLE gate_live_jobs DROP CONSTRAINT gate_live_jobs_pkey",
    "foreign_key": "ALTER TABLE gate_live_jobs DROP CONSTRAINT gate_live_jobs_requested_by_fkey",
    "foreign_key_action": """ALTER TABLE gate_live_jobs DROP CONSTRAINT gate_live_jobs_requested_by_fkey;
        ALTER TABLE gate_live_jobs ADD CONSTRAINT gate_live_jobs_requested_by_fkey
        FOREIGN KEY (requested_by) REFERENCES users(id) ON DELETE CASCADE""",
    "foreign_key_deferral": "ALTER TABLE gate_live_jobs ALTER CONSTRAINT gate_live_jobs_requested_by_fkey DEFERRABLE INITIALLY DEFERRED",
    "foreign_key_validation": """ALTER TABLE gate_live_jobs DROP CONSTRAINT gate_live_jobs_requested_by_fkey;
        ALTER TABLE gate_live_jobs ADD CONSTRAINT gate_live_jobs_requested_by_fkey
        FOREIGN KEY (requested_by) REFERENCES users(id) NOT VALID""",
    "unique_columns": """ALTER TABLE gate_live_jobs DROP CONSTRAINT uq_gate_live_request;
        ALTER TABLE gate_live_jobs ADD CONSTRAINT uq_gate_live_request UNIQUE (request_key)""",
    "unique_nulls": """ALTER TABLE gate_live_jobs DROP CONSTRAINT uq_gate_live_request;
        ALTER TABLE gate_live_jobs ADD CONSTRAINT uq_gate_live_request
        UNIQUE NULLS NOT DISTINCT (requested_by,factory_code,request_key)""",
    "check": "ALTER TABLE gate_live_jobs DROP CONSTRAINT ck_gate_live_job_attempts",
    "nonunique_index": "DROP INDEX ix_gate_live_jobs_device_id",
    "extra_index": "CREATE INDEX unreviewed_hr_index ON gate_live_devices(source_host)",
    "index_include": """DROP INDEX ix_gate_live_jobs_device_id;
        CREATE INDEX ix_gate_live_jobs_device_id ON gate_live_jobs(device_id) INCLUDE (employee_id)""",
    "binding_default": "ALTER TABLE gate_employee_devices ALTER COLUMN mode DROP DEFAULT",
    "binding_nullable": "ALTER TABLE gate_employee_devices ALTER COLUMN mode DROP NOT NULL",
    "binding_check": "ALTER TABLE gate_employee_devices DROP CONSTRAINT gate_gatemode",
    "operation_check": """ALTER TABLE gate_operations DROP CONSTRAINT gate_gatemode;
        ALTER TABLE gate_operations ADD CONSTRAINT gate_gatemode CHECK (mode IN ('disabled','simulator'))""",
    "simulator_check": "ALTER TABLE gate_simulator_devices ADD CONSTRAINT unreviewed_hr_mode CHECK (mode <> 'hikvision')",
}


@pytest.mark.parametrize("fault", FAULTS)
def test_hr_recovery_refuses_storage_drift_and_cleans_only_expected_schema(customer_pg_sessions, fault):
    engine = customer_pg_sessions.kw["bind"]
    with engine.connect() as connection:
        assert contract._approved_target(connection) == "public"
        before = _schemas(connection)
        altered = connection.begin_nested()
        try:
            for statement in FAULTS[fault].split(";"):
                connection.execute(sa.text(statement.strip()))
            with pytest.raises(AssertionError, match="HR recovery .* changed"):
                contract.hr_recovery_drift(connection)
            assert _schemas(connection) == before
        finally:
            altered.rollback()
        assert len(contract.hr_recovery_drift(connection)) == 5
        assert _schemas(connection) == before


def test_hr_recovery_rejects_unapproved_target_namespace_before_expected_ddl(customer_pg_sessions, monkeypatch):
    engine = customer_pg_sessions.kw["bind"]
    instance = contract.load_approved_instance()
    monkeypatch.setattr(contract, "load_approved_instance", lambda: replace(instance, target_prefix="unapproved_hr_"))
    with engine.connect() as connection:
        before = _schemas(connection)
        with pytest.raises(AssertionError, match="outside the approved namespace"):
            contract.hr_recovery_drift(connection)
        assert _schemas(connection) == before
