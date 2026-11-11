"""Exact test-only storage supplement for the unmapped HR recovery image.

Expected storage comes from hash-pinned migration definitions, materialized in
one generated schema inside a savepoint. Nothing is inferred from the schema
under test. The savepoint removes only this helper's generated expected objects.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from sqlalchemy.dialects.postgresql import dialect

from app.tests.pg_approved_instance import CONFIG_ENV, load_approved_instance, preflight_connection


ROOT = Path(__file__).resolve().parents[3]
HEAD = "0157_pricing_gate_live_merge"
LIVE_TABLES = ("gate_live_devices", "gate_live_profiles", "gate_live_jobs")
MODE_TABLES = ("gate_employee_devices", "gate_operations", "gate_simulator_devices")
MODE_CHECK = "mode IN ('disabled', 'simulator', 'hikvision')"
APP_SHA256 = "03f9fc7145eb6ec52a6cbe332d870ed2683edcf678e10e4ba67fdbddb5f0ac13"
MIGRATION_SHA256 = {
    "0156_gate_live_integration.py": "9d301d6e99972e39cdd40c6d4c51e12fd2d13bde612460e4b87a35e7cdf614bf",
    "0157_pricing_gate_live_merge.py": "9d0c445190305909aca6df9ab04e03f0e54842625f31f96cf61c640e972b46b4",
}


def verify_source_pins():
    app = ROOT / "backend/app"
    digest = hashlib.sha256()
    paths = sorted((path for path in app.rglob("*.py")
        if "tests" not in path.relative_to(app).parts and "__pycache__" not in path.parts),
        key=lambda path: path.relative_to(app).as_posix())
    for path in paths:
        digest.update(path.relative_to(app).as_posix().encode() + b"\0"
            + path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    assert digest.hexdigest() == APP_SHA256, "HR recovery runtime source changed"
    for name, wanted in MIGRATION_SHA256.items():
        value = (ROOT / "backend/alembic/versions" / name).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(value).hexdigest() == wanted, "HR recovery frozen migration changed"


def _approved_target(connection):
    """Keep both existing test-owned boundaries, never arbitrary loopback DDL."""
    assert connection.dialect.name == "postgresql", "HR recovery contract requires PostgreSQL"
    schema, database = connection.execute(sa.text("SELECT current_schema(), current_database()")).one()
    url = connection.engine.url
    assert url.get_backend_name() == "postgresql" and not url.query
    assert database == url.database, "HR contract connection database changed"
    if re.fullmatch(r"fresh_migration_[0-9a-f]{32}", schema or ""):
        # This fixture already owns this exact generated schema in its explicit
        # STABILIZATION database. Do not grant a public-schema boundary here.
        raw = os.environ.get("STABILIZATION_POSTGRES_URL")
        assert raw and sa.engine.make_url(raw) == url, "Fresh migration target is not explicitly configured"
        assert url.host in {"127.0.0.1", "localhost", "::1"}
        host, port = connection.execute(sa.text("SELECT host(inet_server_addr()), inet_server_port()")).one()
        assert host in {"127.0.0.1", "::1"} and port == (url.port or 5432)
        if os.environ.get(CONFIG_ENV):
            preflight_connection(connection, load_approved_instance(), database)
    else:
        assert schema == "public", "HR contract requires an owned fixture schema"
        instance = load_approved_instance()
        assert re.fullmatch(re.escape(instance.target_prefix) + r"[0-9a-f]{12}", database), "HR target is outside the approved namespace"
        preflight_connection(connection, instance, database)
    return schema


def _rows(connection, sql, schema, table):
    return [tuple(row) for row in connection.execute(sa.text(sql), {"schema": schema, "table": table})]


def _columns(connection, schema, table):
    return _rows(connection, """
        SELECT a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin,d.adrelid), a.attidentity, a.attgenerated,
               a.attcollation::regcollation::text, a.attndims
        FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        LEFT JOIN pg_attrdef d ON d.adrelid=t.oid AND d.adnum=a.attnum
        WHERE n.nspname=:schema AND t.relname=:table AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum
    """, schema, table)


def _constraints(connection, schema, table, *, mode_only=False):
    predicate = """ AND c.contype='c' AND EXISTS (
        SELECT 1 FROM pg_attribute a WHERE a.attrelid=t.oid
        AND a.attname='mode' AND a.attnum=ANY(c.conkey))""" if mode_only else ""
    return _rows(connection, """
        SELECT c.conname,c.contype,pg_get_constraintdef(c.oid),c.condeferrable,
               c.condeferred,c.convalidated,c.connoinherit,c.conislocal,c.coninhcount,
               c.confupdtype,c.confdeltype,c.confmatchtype
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        JOIN pg_namespace n ON n.oid=t.relnamespace
        WHERE n.nspname=:schema AND t.relname=:table
    """ + predicate + " ORDER BY c.conname", schema, table)


def _table_contract(connection, schema, table):
    return {
        "columns": _columns(connection, schema, table),
        "constraints": _constraints(connection, schema, table),
        "indexes": _rows(connection, """
            SELECT x.relname,pg_get_indexdef(i.indexrelid),i.indisunique,i.indisprimary,
                   i.indisexclusion,i.indimmediate,i.indisvalid,i.indisready,i.indislive,
                   i.indnullsnotdistinct
            FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_class x ON x.oid=i.indexrelid
            WHERE n.nspname=:schema AND t.relname=:table ORDER BY x.relname
        """, schema, table),
        "table": _rows(connection, """
            SELECT t.relkind,t.relpersistence,t.relrowsecurity,t.relforcerowsecurity,
                   t.relreplident,t.relispartition,t.reloptions,t.reltablespace,
                   (SELECT count(*) FROM pg_inherits h WHERE h.inhrelid=t.oid)
            FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=:schema AND t.relname=:table
        """, schema, table),
        "triggers": _rows(connection, """
            SELECT g.tgname,pg_get_triggerdef(g.oid),g.tgenabled
            FROM pg_trigger g JOIN pg_class t ON t.oid=g.tgrelid
            JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE n.nspname=:schema AND t.relname=:table AND NOT g.tgisinternal ORDER BY g.tgname
        """, schema, table),
        "policies": _rows(connection, """
            SELECT policyname,permissive,roles,cmd,qual,with_check FROM pg_policies
            WHERE schemaname=:schema AND tablename=:table ORDER BY policyname
        """, schema, table),
    }


def _normalized(value, expected_schema, actual_schema):
    if isinstance(value, dict):
        return {key: _normalized(item, expected_schema, actual_schema) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized(item, expected_schema, actual_schema) for item in value]
    if isinstance(value, str):
        value = value.replace(expected_schema + ".", actual_schema + ".")
        # A SERIAL default may be unqualified only when its schema is visible.
        # Normalize precisely these three migration-owned sequence references.
        for table in LIVE_TABLES:
            value = value.replace("'" + actual_schema + "." + table + "_id_seq'::regclass",
                "'" + table + "_id_seq'::regclass")
    return value


def _clone_live_table(table, metadata, schema, reference_schema):
    expected = table.to_metadata(metadata, schema=schema,
        referred_schema_fn=lambda *_args: reference_schema)
    # Column(index=True) regenerates its conventional name from the cloned
    # schema's column label. Keep the frozen migration's real index identity;
    # never normalize/truncate an unexpected index name in the tested schema.
    def signature(index):
        return (index.unique, tuple(str(expression.compile(dialect=dialect(),
            compile_kwargs={"include_table": False, "literal_binds": True})) for expression in index.expressions),
            tuple(sorted((key, str(value)) for key, value in index.dialect_kwargs.items())))
    sources = {signature(index): index for index in table.indexes}
    clones = {signature(index): index for index in expected.indexes}
    assert len(sources) == len(table.indexes) and len(clones) == len(expected.indexes), "Frozen HR index clone is ambiguous"
    assert sources.keys() == clones.keys(), "Frozen HR index clone changed its expressions or options"
    for key, index in clones.items():
        index.name = sources[key].name
    return expected


def hr_recovery_drift(connection):
    from app.db.base import Base

    mapped = [name in Base.metadata.tables for name in LIVE_TABLES]
    mapped.append("mode" in Base.metadata.tables["gate_employee_devices"].c)
    if all(mapped):
        return []  # The full application receives no recovery exception.
    assert not any(mapped), "Partial HR recovery mapping is not an approved contract"
    verify_source_pins()
    actual_schema = _approved_target(connection)
    assert MigrationContext.configure(connection).get_current_heads() == (HEAD,)
    name = "qa_hr_contract_" + uuid4().hex
    assert re.fullmatch(r"qa_hr_contract_[0-9a-f]{32}", name)
    nested = connection.begin_nested()
    try:
        connection.execute(sa.schema.CreateSchema(name))
        spec = importlib.util.spec_from_file_location("frozen_hr_recovery_expected",
            ROOT / "backend/alembic/versions/0156_gate_live_integration.py")
        frozen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(frozen)
        metadata = sa.MetaData()
        for stub in frozen.Base.metadata.tables.values():
            if stub.name not in LIVE_TABLES:
                stub.to_metadata(metadata, schema=actual_schema)
        for table in frozen.TABLES:
            expected = _clone_live_table(table, metadata, name, actual_schema)
            expected.create(connection)  # Never create the public/reference stubs.
        mode = sa.Table("gate_employee_devices", metadata,
            sa.Column("mode", sa.String(9), nullable=False, server_default="simulator"),
            sa.CheckConstraint(MODE_CHECK, name="gate_gatemode"), schema=name)
        mode.create(connection)
        for table in LIVE_TABLES:
            expected = _normalized(_table_contract(connection, name, table), name, actual_schema)
            actual = _normalized(_table_contract(connection, actual_schema, table), name, actual_schema)
            differences = {key: {"expected": expected[key], "actual": actual[key]}
                for key in expected if actual[key] != expected[key]}
            assert not differences, f"HR recovery storage changed: {table}: " + json.dumps(differences, sort_keys=True)
        wanted_column = _columns(connection, name, "gate_employee_devices")
        actual_column = [row for row in _columns(connection, actual_schema, "gate_employee_devices") if row[0] == "mode"]
        assert actual_column == wanted_column, "HR recovery binding mode storage changed"
        wanted_check = _constraints(connection, name, "gate_employee_devices", mode_only=True)
        for table in MODE_TABLES:
            assert _constraints(connection, actual_schema, table, mode_only=True) == wanted_check, "HR recovery mode check changed"
    finally:
        nested.rollback()
    return [
        *[["remove_table", table] for table in LIVE_TABLES],
        ["remove_index", {"index": "ix_gate_live_jobs_device_id", "table": "gate_live_jobs",
            "unique": False, "expressions": ["gate_live_jobs.device_id"], "options": {}}],
        ["remove_column", None, "gate_employee_devices", {"column": "mode", "type": "VARCHAR(9)",
            "nullable": False, "default": "'simulator'::character varying"}],
    ]
