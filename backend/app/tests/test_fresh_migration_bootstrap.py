"""Frozen bootstrap and opt-in PostgreSQL QA against reviewed known schema drift."""

import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
KNOWN_DRIFT = VERSIONS.parents[2] / "docs" / "audit-evidence" / "fresh-migration-schema-drift.json"


def load_migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_initial_bootstrap_does_not_precreate_revision_0039_table():
    """The first migration must leave later-owned tables for their own DDL.

    This is the minimal collision reproducer, not full PostgreSQL-chain QA:
    revisions 0002-0038 do not create manual_accessory_issues.
    """
    initial = load_migration("0001_initial")
    accessory_issues = load_migration("0039_manual_accessory_issues")
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                initial.upgrade()
                accessory_issues.upgrade()
            inspector = sa.inspect(connection)
            assert "manual_accessory_issues" in inspector.get_table_names()
            assert {index["name"] for index in inspector.get_indexes("manual_accessory_issues")} == {
                "ix_manual_accessory_issues_item_id",
                "ix_manual_accessory_issues_production_order_id",
            }
    finally:
        engine.dispose()


def test_initial_upgrade_and_downgrade_ignore_current_application_metadata(monkeypatch):
    from app.db.base import Base

    future_metadata = sa.MetaData()
    future_table = sa.Table("synthetic_future_model", future_metadata, sa.Column("id", sa.Integer, primary_key=True))
    monkeypatch.setattr(Base, "metadata", future_metadata)
    initial = load_migration("0001_initial")
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                initial.upgrade()
                inspector = sa.inspect(connection)
                tables = set(inspector.get_table_names())
                assert len(tables) == 54
                assert {"cutting_passports", "sewing_flows", "sewing_assignments", "password_reset_tokens"} <= tables
                assert not tables & {"synthetic_future_model", "manual_accessory_issues", "eco_fabric_dispatches"}
                audit = {column["name"]: column for column in inspector.get_columns("audit_logs")}
                for name in ("prev_hash", "entry_hash"):
                    assert audit[name]["nullable"] and audit[name]["type"].length == 64
                assert "ix_audit_logs_entry_hash" in {index["name"] for index in inspector.get_indexes("audit_logs")}

                future_table.create(connection)
                initial.downgrade()
                assert sa.inspect(connection).get_table_names() == ["synthetic_future_model"]
    finally:
        engine.dispose()


@pytest.fixture
def postgres_migrations(monkeypatch):
    """Never starts a server; opt in only to an explicitly disposable loopback DB.

    The suite runner provides STABILIZATION_POSTGRES_URL. Every test creates and
    removes its own schema; the application fixture continues to use SQLite.
    Route Alembic's engine factory to this schema because env.py does not accept
    an externally supplied connection. Actual env.py and all revisions still run.
    """
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for disposable PostgreSQL migration coverage")
    url = sa.engine.make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"} or url.query:
        pytest.fail("Migration tests require a loopback PostgreSQL URL without connection overrides")
    schema = f"fresh_migration_{uuid4().hex}"
    engine = sa.create_engine(
        url, poolclass=sa.pool.NullPool,
        connect_args={"options": f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=20000"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        from app.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", url.render_as_string(hide_password=False))
        monkeypatch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
        config = Config(str(VERSIONS.parents[1] / "alembic.ini"))
        yield SimpleNamespace(engine=engine, config=config)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _current_revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _compare_json_server_default(context, inspected, model, inspected_default, _model_default, model_default):
    """PostgreSQL JSON has no equality operator; retain actual default checks."""
    if not isinstance(model.type, sa.JSON):
        return None
    if inspected_default is None or model_default is None:
        return inspected_default != model_default
    literal = re.compile(r"^'((?:[^']|'')*)'(?:::\s*jsonb?)?$", re.IGNORECASE)

    def normalized(value):
        quoted = literal.fullmatch(value.strip())
        text = quoted[1].replace("''", "'") if quoted else value
        # Alembic renders JSON server_default="[]" without SQL quotes. Canonical
        # JSON also distinguishes booleans from numbers (Python True == 1).
        return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))

    try:
        return normalized(inspected_default) != normalized(model_default)
    except json.JSONDecodeError:
        pass  # Non-literal defaults retain a real PostgreSQL JSONB comparison.
    return context.connection.scalar(sa.text(
        f"SELECT ({inspected_default})::jsonb IS DISTINCT FROM ({model_default})::jsonb"
    ))


@pytest.mark.parametrize(("database_default", "model_default", "different"), [
    ("'[]'::json", "'[]'", False),
    ("'[]'::json", "[]", False),
    ("'{\"a\": 1, \"b\": 2}'::json", "'{\"b\":2,\"a\":1}'", False),
    ("'[]'::json", "'{}'", True),
    ("'[]'::json", None, True),
    ("'[true]'::json", "[1]", True),
])
def test_json_default_comparison_preserves_meaning(database_default, model_default, different):
    column = sa.Column("payload", sa.JSON())
    assert _compare_json_server_default(None, column, column, database_default, None, model_default) is different


def _describe_difference(value):
    """Stable, complete QA output instead of object addresses in repr()."""
    if isinstance(value, (list, tuple)):
        return [_describe_difference(item) for item in value]
    if isinstance(value, dict):
        return {key: _describe_difference(item) for key, item in value.items()}
    if isinstance(value, sa.Column):
        return {"column": value.name, "type": str(value.type), "nullable": value.nullable,
                "default": _describe_difference(value.server_default)}
    if isinstance(value, sa.Index):
        return {"index": value.name, "table": value.table.name, "unique": value.unique,
                "expressions": [str(item) for item in value.expressions],
                "options": {key: str(item) for key, item in value.dialect_kwargs.items()}}
    if isinstance(value, sa.Constraint):
        result = {"constraint": type(value).__name__, "name": value.name, "table": value.table.name,
                  "columns": [column.name for column in value.columns]}
        if isinstance(value, sa.ForeignKeyConstraint):
            result.update(targets=[element.target_fullname for element in value.elements],
                          ondelete=value.ondelete, onupdate=value.onupdate)
        return result
    if isinstance(value, sa.DefaultClause):
        return str(value.arg)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _known_drift_baseline():
    report = json.loads(KNOWN_DRIFT.read_text(encoding="utf-8"))
    return [entry["difference"] for entry in report["differences"]]


def _assert_known_drift_baseline(actual, expected):
    """Require exact reviewed drift, independent only of top-level/key order."""
    def canonical(differences):
        return sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in differences)

    assert canonical(actual) == canonical(expected), (
        "Known schema drift changed: review added, changed or disappearing differences; "
        "do not automatically regenerate the DB08 baseline"
    )


def test_known_drift_baseline_ignores_only_order():
    expected = _known_drift_baseline()
    assert len(expected) == 126
    _assert_known_drift_baseline(list(reversed(expected)), expected)


@pytest.mark.parametrize("change", ["added", "changed", "disappeared", "duplicated"])
def test_known_drift_baseline_rejects_unreviewed_change(change):
    expected = _known_drift_baseline()
    actual = json.loads(json.dumps(expected))
    if change == "added":
        actual.append(["add_column", None, "models", {"column": "synthetic_new_column"}])
    elif change == "changed":
        actual[0][1]["unique"] = not actual[0][1]["unique"]
    elif change == "disappeared":
        actual.pop()
    else:
        actual.append(actual[0])
    with pytest.raises(AssertionError, match="Known schema drift changed"):
        _assert_known_drift_baseline(actual, expected)


def _assert_schema_contract_with_known_drift(engine):
    """Check mapped storage and the exact reviewed known-drift baseline.

    Generated model lookup columns are deliberately migration-owned (0084);
    they are queried as SQL and have no ORM Columns. All 126 remaining diffs,
    including defaults, must match the reviewed report exactly. Thirty entries
    remain unresolved under DB08; passing this check does not claim ORM parity.
    """
    from app.db.base import Base
    import app.models  # noqa: F401 - register model metadata for comparison

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert set(Base.metadata.tables) <= tables, "Missing ORM-mapped tables"
        for table in Base.metadata.tables.values():
            columns = {column["name"] for column in inspector.get_columns(table.name)}
            assert set(table.columns.keys()) <= columns, f"Missing ORM-mapped columns in {table.name}"
        context = MigrationContext.configure(connection, opts={
            "compare_type": True, "compare_server_default": _compare_json_server_default,
        })
        differences = compare_metadata(context, Base.metadata)
        known_drift = []
        generated_keys_seen = set()
        for difference in differences:
            if (isinstance(difference, tuple) and difference[0] == "remove_column"
                    and difference[2] == "models" and difference[3].name in {"model_group_key", "is_legacy_import"}):
                column = difference[3]
                expected_type = sa.Text if column.name == "model_group_key" else sa.Boolean
                assert isinstance(column.type, expected_type) and column.computed is not None and column.computed.persisted
                generated_keys_seen.add(column.name)
            else:
                known_drift.append(difference)
        assert generated_keys_seen == {"model_group_key", "is_legacy_import"}, "0084 must preserve its generated lookup columns"
        normalized = _describe_difference(known_drift)
        print("KNOWN_SCHEMA_DRIFT=" + json.dumps(normalized, sort_keys=True))
        _assert_known_drift_baseline(normalized, _known_drift_baseline())


def test_postgres_fresh_head_rerun_and_known_drift_baseline(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    assert sa.inspect(engine).get_table_names() == []

    command.upgrade(config, "head")

    assert _current_revision(engine) == ScriptDirectory.from_config(config).get_current_head() == "0131_sewing_corrections"
    tables = set(sa.inspect(engine).get_table_names())
    assert {"manual_accessory_issues", "eco_fabric_dispatches", "sewing_records"} <= tables
    mutations = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().split(None, 1)[0].upper() in {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE"}:
            mutations.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        command.upgrade(config, "head")
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    assert mutations == []
    _assert_schema_contract_with_known_drift(engine)


def test_postgres_upgrade_from_0130_preserves_existing_rows(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0130_eco_fabric_transfers")
    metadata = sa.MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection)

        def insert(table, **values):
            row = metadata.tables[table]
            return connection.execute(row.insert().values(**values).returning(row.c.id)).scalar_one()

        department_id = insert("departments", name="Synthetic migration department", code="TEST-MIG")
        model_id = insert("models", code="TEST-MIG", name="Synthetic migration model", status="draft", sam_minutes=0)
        order_id = insert("production_orders", production_no="PO-MIG-TEST", production_type="branded_stock",
                          model_id=model_id, status="sewing", planned_quantity=2)
        work_id = insert("work_orders", production_order_id=order_id, department_id=department_id,
                         operation="sewing", status="in_progress", planned_input_qty=2, planned_output_qty=2,
                         actual_input_qty=2, actual_output_qty=2, passed_qty=2, failed_qty=0, rework_qty=0,
                         is_blocked=False)
        record_id = insert("sewing_records", work_order_id=work_id, input_qty=2, sewn_qty=2, passed_qty=2,
                           failed_qty=0, rework_qty=0, rejected_qty=0, notes="Preserve this existing row")
        record = metadata.tables["sewing_records"]
        before = dict(connection.execute(sa.select(record).where(record.c.id == record_id)).mappings().one())

    command.upgrade(config, "head")

    assert _current_revision(engine) == "0131_sewing_corrections"
    with engine.connect() as connection:
        current = sa.Table("sewing_records", sa.MetaData(), autoload_with=connection)
        after = dict(connection.execute(sa.select(current).where(current.c.id == record_id)).mappings().one())
    assert {key: after[key] for key in before} == before
    assert after["correction_version"] == 0
    assert after["sewing_assignment_id"] is None and after["assignment_applied_qty"] is None
