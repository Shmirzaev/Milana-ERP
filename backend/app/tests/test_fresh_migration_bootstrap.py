"""Frozen bootstrap and opt-in PostgreSQL QA against reviewed known schema drift."""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command, op
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.migrations.bootstrap_guards import (
    create_index_if_missing_by_signature,
    find_equivalent_duplicates,
    index_signature,
    object_signatures,
)


VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
KNOWN_DRIFT = VERSIONS.parents[2] / "docs" / "audit-evidence" / "fresh-migration-schema-drift.json"
COMPAT_HEAD = "0150_package_customer_release"
COMPAT_GATE_SHA256 = "5ef93b3954aaf935107b155921ac722133cbfd43a06cb29064d06e8594c1c764"
COMPAT_MIGRATION_SHA256 = "17d24d19f0d49ecc2bc9ab78108aede5043a5e2e081355ffb6e13583a9901372"


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


def _compatibility_release_drift(connection):
    """One reviewed migration-owned table on the exact old-runtime rollback image.

    Keep the shared 94-entry baseline untouched. The full feature maps this table
    and receives no supplement. Exact source hashes make this a reviewed exception,
    while a reflected storage contract prevents name-only remove_table output from
    concealing added/changed columns, constraints, defaults or indexes.
    """
    root = VERSIONS.parents[2]
    gate = root / "scripts" / "test_rollback_image_schema_0150.py"
    feature = root / "backend" / "app" / "models" / "fulfillment" / "package_customer_service.py"
    if not gate.is_file() or feature.exists():
        return []
    assert hashlib.sha256(gate.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == COMPAT_GATE_SHA256
    migration = VERSIONS / "0150_package_customer_release.py"
    assert hashlib.sha256(migration.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == COMPAT_MIGRATION_SHA256
    assert MigrationContext.configure(connection).get_current_heads() == (COMPAT_HEAD,)
    from app.db.base import Base

    table = "package_customer_releases"
    assert table not in Base.metadata.tables, "Compatibility runtime must remain unmapped"
    inspector = sa.inspect(connection)
    assert table in inspector.get_table_names(), "Reviewed compatibility ledger is missing"
    columns = inspector.get_columns(table)
    assert [(column["name"], str(column["type"]), column["nullable"], column["default"]) for column in columns] == [
        ("package_id", "INTEGER", False, None),
        ("source_order_ids", "JSON", False, None),
        ("released_quantity", "INTEGER", False, None),
        ("released_by", "INTEGER", False, None),
        ("released_at", "TIMESTAMP", False, "now()"),
        ("reason", "VARCHAR(1000)", False, None),
    ], "Compatibility ledger columns/types/nullability/defaults changed"
    assert columns[4]["type"].timezone is True
    assert all(column.get("computed") is None and column.get("identity") is None for column in columns)
    assert inspector.get_pk_constraint(table)["constrained_columns"] == ["package_id"]
    foreign_keys = inspector.get_foreign_keys(table)
    assert len(foreign_keys) == 2
    assert {(
        tuple(key["constrained_columns"]), key["referred_schema"], key["referred_table"],
        tuple(key["referred_columns"]), tuple(sorted(key["options"].items())),
    ) for key in foreign_keys} == {
        (("package_id",), None, "packages", ("id",), (("ondelete", "CASCADE"),)),
        (("released_by",), None, "users", ("id",), ()),
    }, "Compatibility ledger foreign-key contract changed"
    checks = inspector.get_check_constraints(table)
    assert len(checks) == 1 and checks[0]["name"] == "ck_package_customer_release_quantity"
    assert re.sub(r"[\s()]", "", checks[0]["sqltext"]) == "released_quantity>0"
    assert not checks[0].get("dialect_options")
    assert inspector.get_unique_constraints(table) == [] and inspector.get_indexes(table) == []
    return [["remove_table", table]]


PRICING_RECOVERY_COLUMNS = [
    ("active_model_id", "INTEGER", True, None),
    ("workflow_state", "VARCHAR(32)", False, "'legacy'::character varying"),
    ("factory_code", "VARCHAR(3)", True, None),
    ("revision", "INTEGER", False, "1"),
    ("materials_json", "JSON", False, "'[]'::json"),
    ("passport_snapshot_json", "JSON", True, None),
    ("purchasing_submitted_at", "TIMESTAMP", True, None),
    ("accessories_submitted_at", "TIMESTAMP", True, None),
    ("no_accessories_reason", "TEXT", True, None),
    ("printing_cost", "NUMERIC(14, 4)", True, None),
    ("correction_team", "VARCHAR(16)", True, None),
    ("correction_reason", "TEXT", True, None),
    ("approved_at", "TIMESTAMP", True, None),
    ("approved_by_id", "INTEGER", True, None),
    ("approval_snapshot_json", "JSON", True, None),
    ("price_baseline_json", "JSON", True, None),
]


def _pricing_recovery_drift(connection):
    """Exact migration0156 storage contract on the deliberately unmapped old ORM.

    Never regenerate or loosen the shared 94-entry DB08 baseline. The full
    application maps these fields and gets no supplement. Recovery keeps its old
    business code, guards all pricing routes and separately proves actual image
    startup; this check verifies every additional storage object, including checks
    and timestamp zones that Alembic's normalized diff would otherwise omit.
    """
    from app.schemas import PriceCalculationRequest

    table = "price_calculation_requests"
    mapped = set(PriceCalculationRequest.__table__.columns.keys())
    names = {row[0] for row in PRICING_RECOVERY_COLUMNS}
    if names.intersection(mapped):
        return []
    root = VERSIONS.parents[2]
    for relative, digest in {
        "backend/alembic/versions/0156_variant_price_workflow.py": "b44bcabad65c8b8d844f9bbaeafda421b23d74e864abae9956a324641652e242",
        "backend/app/core/pricing_recovery.py": "2db579b873c32de3534349654bbb3050d5e38db55b777a2dc856e838e2d38e7e",
        "backend/app/schemas/planning/price_calculation.py": "96f5f88110eb1a8021c7da97ca7835b9908dda044717d32e1e0a055680ed765f",
    }.items():
        assert hashlib.sha256((root / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest
    assert MigrationContext.configure(connection).get_current_heads() == ("0156_variant_price_workflow",)
    inspector = sa.inspect(connection)
    extra = {column["name"]: column for column in inspector.get_columns(table) if column["name"] not in mapped}
    assert set(extra) == names, "Pricing recovery storage columns changed"
    for name, kind, nullable, default in PRICING_RECOVERY_COLUMNS:
        column = extra[name]
        assert (str(column["type"]), column["nullable"], column["default"]) == (kind, nullable, default), "Pricing recovery column contract changed"
        assert not column.get("computed") and not column.get("identity")
        if kind == "TIMESTAMP":
            assert column["type"].timezone is True
    foreign = [key for key in inspector.get_foreign_keys(table) if names.intersection(key["constrained_columns"])]
    assert {(key["name"], tuple(key["constrained_columns"]), key["referred_schema"], key["referred_table"], tuple(key["referred_columns"]), tuple(sorted(key["options"].items()))) for key in foreign} == {
        ("fk_price_active_model", ("active_model_id",), None, "models", ("id",), ()),
        ("fk_price_approved_by", ("approved_by_id",), None, "users", ("id",), ()),
    }, "Pricing recovery foreign keys changed"
    unique = [key for key in inspector.get_unique_constraints(table) if names.intersection(key["column_names"])]
    assert [(key["name"], key["column_names"]) for key in unique] == [("uq_price_active_model", ["active_model_id"])], "Pricing recovery unique constraint changed"
    unique_options = dict(unique[0].get("dialect_options", {}))
    for key, implicit in [("postgresql_include", []), ("postgresql_nulls_not_distinct", False)]:
        if unique_options.get(key) == implicit:
            unique_options.pop(key)
    assert not unique_options, "Pricing recovery uniqueness semantics changed"
    constraints = connection.execute(sa.text("""
        SELECT conname, condeferrable, condeferred, convalidated
        FROM pg_constraint WHERE conrelid='price_calculation_requests'::regclass
        AND conname IN ('fk_price_active_model','fk_price_approved_by','uq_price_active_model',
                        'ck_price_active_variant','ck_price_workflow_state')
    """)).all()
    assert len(constraints) == 5 and all(not row.condeferrable and not row.condeferred and row.convalidated for row in constraints), "Pricing recovery constraint timing/validation changed"
    indexes = [index for index in inspector.get_indexes(table) if names.intersection(index["column_names"]) and not index.get("duplicates_constraint")]
    def index_options(index):
        options = dict(index.get("dialect_options", {}))
        # Newer SQLAlchemy reflects the implicit empty INCLUDE explicitly.
        if options.get("postgresql_include") == []:
            options.pop("postgresql_include")
        return json.dumps(options, sort_keys=True)
    assert {(index["name"], tuple(index["column_names"]), index["unique"], index_options(index)) for index in indexes} == {
        ("ix_price_calculation_requests_factory_code", ("factory_code",), False, "{}"),
        ("ix_price_calculation_requests_workflow_state", ("workflow_state",), False, "{}"),
    }, "Pricing recovery indexes changed"
    checks = {key["name"]: key["sqltext"] for key in inspector.get_check_constraints(table)}
    assert checks == {
        "ck_price_active_variant": "active_model_id IS NULL OR active_model_id = model_id",
        "ck_price_workflow_state": "workflow_state::text = ANY (ARRAY['legacy'::character varying, 'collecting'::character varying, 'awaiting_finance'::character varying, 'approved'::character varying, 'cancelled'::character varying]::text[])",
    }, "Pricing recovery checks changed"
    differences = [["remove_column", None, table, {"column": name, "type": kind, "nullable": nullable, "default": default}] for name, kind, nullable, default in PRICING_RECOVERY_COLUMNS]
    for name, column, target in [("fk_price_active_model", "active_model_id", "models.id"), ("fk_price_approved_by", "approved_by_id", "users.id")]:
        differences.append(["remove_fk", {"constraint": "ForeignKeyConstraint", "name": name, "table": table, "columns": [column], "targets": [target], "ondelete": None, "onupdate": None}])
    differences.append(["remove_constraint", {"constraint": "UniqueConstraint", "name": "uq_price_active_model", "table": table, "columns": ["active_model_id"]}])
    for column in ["factory_code", "workflow_state"]:
        differences.append(["remove_index", {"index": "ix_price_calculation_requests_" + column, "table": table, "unique": False, "expressions": [table + "." + column], "options": {}}])
    return differences


def test_known_drift_baseline_ignores_only_order():
    expected = _known_drift_baseline()
    assert len(expected) == 94
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
    they are queried as SQL and have no ORM Columns. All 94 remaining diffs,
    including defaults, must match the reviewed report exactly. All 21 DB08 entries have explicit resolutions in
    resolved_by_ismail_completion; passing this check does not claim global ORM
    parity. Entries 90-95 of the previous baseline were removed deliberately by
    187933b9, which aligned the sales order item ORM to shipped migration 0071,
    and the Beyka table plus its two indexes were removed by 25192d17, which
    mapped cutting_beika_material_usages; see the `resolved_by_db08` and
    `resolved_by_db08_beyka` blocks in the baseline for exactly what was removed.
    """
    from app.db.base import Base
    import app.schemas  # noqa: F401 - register model metadata for comparison

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
        _assert_known_drift_baseline(normalized, _known_drift_baseline() + _compatibility_release_drift(connection) + _pricing_recovery_drift(connection))


@pytest.mark.parametrize("change", ["extra_column", "nullable", "type", "default", "foreign_key", "unique", "unique_nulls", "deferred_unique", "check", "index"])
def test_postgres_pricing_recovery_contract_rejects_storage_drift(postgres_migrations, change):
    from app.schemas import PriceCalculationRequest

    if {row[0] for row in PRICING_RECOVERY_COLUMNS}.intersection(PriceCalculationRequest.__table__.columns.keys()):
        pytest.skip("Exact old-runtime pricing recovery candidate only")
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "head")
    statements = {
        "extra_column": "ALTER TABLE price_calculation_requests ADD COLUMN unreviewed TEXT",
        "nullable": "ALTER TABLE price_calculation_requests ALTER COLUMN revision DROP NOT NULL",
        "type": "ALTER TABLE price_calculation_requests ALTER COLUMN correction_reason TYPE varchar(900)",
        "default": "ALTER TABLE price_calculation_requests ALTER COLUMN revision SET DEFAULT 2",
        "foreign_key": "ALTER TABLE price_calculation_requests DROP CONSTRAINT fk_price_approved_by",
        "unique": "ALTER TABLE price_calculation_requests DROP CONSTRAINT uq_price_active_model",
        "unique_nulls": "ALTER TABLE price_calculation_requests DROP CONSTRAINT uq_price_active_model; ALTER TABLE price_calculation_requests ADD CONSTRAINT uq_price_active_model UNIQUE NULLS NOT DISTINCT (active_model_id)",
        "deferred_unique": "ALTER TABLE price_calculation_requests DROP CONSTRAINT uq_price_active_model; ALTER TABLE price_calculation_requests ADD CONSTRAINT uq_price_active_model UNIQUE (active_model_id) DEFERRABLE INITIALLY DEFERRED",
        "check": "ALTER TABLE price_calculation_requests DROP CONSTRAINT ck_price_active_variant",
        "index": "DROP INDEX ix_price_calculation_requests_workflow_state",
    }
    with engine.begin() as connection:
        assert len(_pricing_recovery_drift(connection)) == 21
        connection.exec_driver_sql(statements[change])
        with pytest.raises(AssertionError, match="Pricing recovery"):
            _pricing_recovery_drift(connection)


@pytest.mark.parametrize("change", ["added", "missing", "changed", "duplicated"])
def test_compatibility_drift_supplement_rejects_unreviewed_differences(change):
    expected = _known_drift_baseline() + [["remove_table", "package_customer_releases"]]
    actual = json.loads(json.dumps(expected))
    if change == "added":
        actual.append(["remove_table", "unreviewed_table"])
    elif change == "missing":
        actual.pop()
    elif change == "changed":
        actual[-1] = ["remove_table", "other_table"]
    else:
        actual.append(actual[-1])
    with pytest.raises(AssertionError, match="Known schema drift changed"):
        _assert_known_drift_baseline(actual, expected)


@pytest.mark.parametrize("change", ["missing_table", "extra_column", "nullable", "type", "default", "foreign_key", "check"])
def test_postgres_compatibility_ledger_contract_rejects_storage_drift(postgres_migrations, change):
    root = VERSIONS.parents[2]
    if not (root / "scripts" / "test_rollback_image_schema_0150.py").is_file() or (
            root / "backend" / "app" / "models" / "fulfillment" / "package_customer_service.py").exists():
        pytest.skip("Exact old-runtime schema-0150 compatibility candidate only")
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert _compatibility_release_drift(connection) == [["remove_table", "package_customer_releases"]]
        table = "package_customer_releases"
        statements = {
            "missing_table": f"DROP TABLE {table}",
            "extra_column": f"ALTER TABLE {table} ADD COLUMN unexpected INTEGER",
            "nullable": f"ALTER TABLE {table} ALTER COLUMN reason DROP NOT NULL",
            "type": f"ALTER TABLE {table} ALTER COLUMN reason TYPE VARCHAR(999)",
            "default": f"ALTER TABLE {table} ALTER COLUMN released_at DROP DEFAULT",
            "check": f"ALTER TABLE {table} DROP CONSTRAINT ck_package_customer_release_quantity",
        }
        if change == "foreign_key":
            key = next(key for key in sa.inspect(connection).get_foreign_keys(table) if key["constrained_columns"] == ["package_id"])
            quoted = connection.dialect.identifier_preparer.quote(key["name"])
            connection.exec_driver_sql(f"ALTER TABLE {table} DROP CONSTRAINT {quoted}")
            connection.exec_driver_sql(f"ALTER TABLE {table} ADD FOREIGN KEY (package_id) REFERENCES packages(id) ON DELETE RESTRICT")
        else:
            connection.exec_driver_sql(statements[change])
        with pytest.raises(AssertionError):
            _compatibility_release_drift(connection)


def test_postgres_fresh_head_rerun_and_known_drift_baseline(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    assert sa.inspect(engine).get_table_names() == []

    command.upgrade(config, "head")

    assert _current_revision(engine) == ScriptDirectory.from_config(config).get_current_head()
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

    assert _current_revision(engine) == ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = sa.Table("sewing_records", sa.MetaData(), autoload_with=connection)
        after = dict(connection.execute(sa.select(current).where(current.c.id == record_id)).mappings().one())
    assert {key: after[key] for key in before} == before
    assert after["correction_version"] == 0
    assert after["sewing_assignment_id"] is None and after["assignment_applied_qty"] is None


# --------------------------------------------------------------------------- #
# DB06: signature-based bootstrap guards for equivalent duplicate objects
# --------------------------------------------------------------------------- #
# 0025_material_reservations creates UniqueConstraint("reservation_no") at :57
# and then asks _create_index_if_missing for a separate unique index over the
# same column at :61. A name-only guard cannot see that the table it just
# created already enforces uniqueness, so a fresh schema carries both objects.
# Applied migrations are immutable history, so these tests never edit 0025: they
# pin the signature guard that fresh-bootstrap DDL is expected to use, and prove
# against real PostgreSQL 17.11 that it suppresses the redundant index.

RESERVATIONS = "material_reservations"
RESERVATION_CONSTRAINT = "uq_material_reservations_reservation_no"
RESERVATION_INDEX = "ix_material_reservations_reservation_no"


def _unique_objects(connection, table=RESERVATIONS):
    """Real catalog evidence: unique constraints and unique indexes, by name."""
    inspector = sa.inspect(connection)
    constraints = {item["name"] for item in inspector.get_unique_constraints(table)}
    indexes = {
        item["name"] for item in inspector.get_indexes(table)
        if item.get("unique") and not item.get("duplicates_constraint")
    }
    return constraints, indexes


def test_signature_makes_a_unique_constraint_and_index_equivalent():
    """The core of the guard: meaning, not name."""
    constraint_side = index_signature(RESERVATIONS, ["reservation_no"], unique=True)
    assert constraint_side == index_signature(RESERVATIONS, ["reservation_no"], unique=True)
    # Order and uniqueness are part of the signature.
    assert constraint_side != index_signature(
        RESERVATIONS, ["reservation_no", "id"], unique=True
    )
    assert constraint_side != index_signature(RESERVATIONS, ["reservation_no"], unique=False)
    assert constraint_side != index_signature(
        "other_table", ["reservation_no"], unique=True
    )
    # A partial unique index does not cover a plain one.
    assert constraint_side != index_signature(
        RESERVATIONS, ["reservation_no"], unique=True, where="status = 'reserved'"
    )


def test_guard_skips_a_redundant_unique_index_covered_by_a_constraint():
    """The name-only guard would create here; the signature guard must not."""
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {RESERVATIONS} ("
                "id INTEGER PRIMARY KEY, reservation_no VARCHAR(64) NOT NULL, "
                f"status VARCHAR(32), CONSTRAINT {RESERVATION_CONSTRAINT} "
                "UNIQUE (reservation_no))"
            )
            inspector = sa.inspect(connection)
            created: list[str] = []
            plan = create_index_if_missing_by_signature(
                inspector, RESERVATION_INDEX, RESERVATIONS, ["reservation_no"],
                unique=True, create=lambda *a, **k: created.append(a[0]),
            )
            assert plan.action == "skipped_equivalent"
            assert plan.covered_by == RESERVATION_CONSTRAINT
            assert created == [], "guard must not emit a redundant unique index"
            _, indexes = _unique_objects(connection)
            assert indexes == set()
    finally:
        engine.dispose()


def test_guard_creates_an_index_when_nothing_equivalent_exists():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {RESERVATIONS} ("
                "id INTEGER PRIMARY KEY, reservation_no VARCHAR(64) NOT NULL)"
            )
            inspector = sa.inspect(connection)
            plan = create_index_if_missing_by_signature(
                inspector, RESERVATION_INDEX, RESERVATIONS, ["reservation_no"],
                unique=True, create=lambda *a, **k: connection.exec_driver_sql(
                    f"CREATE UNIQUE INDEX {a[0]} ON {a[1]} ({a[2][0]})"
                ),
            )
            assert plan.action == "created"
            constraints, indexes = _unique_objects(connection)
            assert indexes == {RESERVATION_INDEX}
            assert constraints == set()
    finally:
        engine.dispose()


def test_guard_with_no_create_callable_is_read_only():
    """``create=None`` must plan without touching the database."""
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {RESERVATIONS} ("
                "id INTEGER PRIMARY KEY, reservation_no VARCHAR(64) NOT NULL)"
            )
            inspector = sa.inspect(connection)
            before = set(inspector.get_indexes(RESERVATIONS))
            plan = create_index_if_missing_by_signature(
                inspector, RESERVATION_INDEX, RESERVATIONS, ["reservation_no"],
                unique=True,
            )
            assert plan.action == "would_create"
            assert set(sa.inspect(connection).get_indexes(RESERVATIONS)) == before
    finally:
        engine.dispose()


def test_duplicate_audit_reports_nothing_when_objects_are_distinct():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {RESERVATIONS} ("
                "id INTEGER PRIMARY KEY, reservation_no VARCHAR(64) NOT NULL, "
                "status VARCHAR(32), "
                f"CONSTRAINT {RESERVATION_CONSTRAINT} UNIQUE (reservation_no))"
            )
            connection.exec_driver_sql(
                f"CREATE INDEX ix_material_reservations_status ON {RESERVATIONS} (status)"
            )
            assert find_equivalent_duplicates(sa.inspect(connection), [RESERVATIONS]) == []
    finally:
        engine.dispose()


def test_duplicate_audit_reports_the_constraint_and_index_pair():
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {RESERVATIONS} ("
                "id INTEGER PRIMARY KEY, reservation_no VARCHAR(64) NOT NULL, "
                f"CONSTRAINT {RESERVATION_CONSTRAINT} UNIQUE (reservation_no))"
            )
            connection.exec_driver_sql(
                f"CREATE UNIQUE INDEX {RESERVATION_INDEX} ON {RESERVATIONS} (reservation_no)"
            )
            duplicates = find_equivalent_duplicates(sa.inspect(connection), [RESERVATIONS])
            assert len(duplicates) == 1
            assert duplicates[0].columns == ("reservation_no",)
            assert {duplicates[0].kept, duplicates[0].redundant} == {
                RESERVATION_CONSTRAINT, RESERVATION_INDEX,
            }
    finally:
        engine.dispose()


@pytest.fixture
def reservations_postgres(monkeypatch):
    """A disposable loopback schema holding a freshly bootstrapped 0025 table.

    Runs the real 0024 -> 0025 part of the real chain, then 0025's own
    ``upgrade()`` through Alembic, so the DDL under test is the migration's
    actual fresh-bootstrap DDL and not ``create_all``.
    """
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for disposable PostgreSQL migration coverage")
    url = sa.engine.make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Bootstrap guard tests require a loopback PostgreSQL URL")
    schema = f"db06_guard_{uuid4().hex}"
    engine = sa.create_engine(
        url, poolclass=sa.pool.NullPool,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        from app.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", url.render_as_string(hide_password=False))
        monkeypatch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
        config = Config(str(VERSIONS.parents[1] / "alembic.ini"))
        command.upgrade(config, "0024_payroll")
        yield SimpleNamespace(engine=engine, monkeypatch=monkeypatch)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _run_0025_upgrade(engine, monkeypatch=None):
    """Run the real 0025 ``upgrade()`` against ``engine``."""
    migration = load_migration("0025_material_reservations")
    if monkeypatch is not None:
        def guarded(inspector, name, table_name, columns, unique=False):
            return create_index_if_missing_by_signature(
                inspector, name, table_name, columns, unique=unique, create=op.create_index,
            )

        monkeypatch.setattr(migration, "_create_index_if_missing", guarded)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()


def test_postgres_0025_fresh_bootstrap_still_emits_the_duplicate(reservations_postgres):
    """Documents the live DB06 defect: history emits both objects.

    0025 is immutable and production has run it, so the duplicate is real and
    persists until decision D2 approves a cleanup. The guard below prevents it
    on a fresh bootstrap; it does not retroactively remove this.
    """
    engine = reservations_postgres.engine
    _run_0025_upgrade(engine)

    with engine.connect() as connection:
        constraints, indexes = _unique_objects(connection)
        assert RESERVATION_CONSTRAINT in constraints
        assert RESERVATION_INDEX in indexes
        duplicates = find_equivalent_duplicates(
            sa.inspect(connection), [RESERVATIONS]
        )
        assert len(duplicates) == 1
        assert {duplicates[0].kept, duplicates[0].redundant} == {
            RESERVATION_CONSTRAINT, RESERVATION_INDEX,
        }
        # Real catalog proof: two separate unique btree indexes on one column.
        physical = connection.execute(sa.text(
            "select indexname from pg_indexes where schemaname = current_schema() "
            "and tablename = :table and indexdef like '%UNIQUE%' "
            "and indexname != 'material_reservations_pkey'"
        ), {"table": RESERVATIONS}).scalars().all()
        assert set(physical) == {RESERVATION_CONSTRAINT, RESERVATION_INDEX}


def test_postgres_0025_fresh_bootstrap_with_signature_guard_emits_no_duplicate(
    reservations_postgres,
):
    """The same real migration, with the guard in place of the name-only helper."""
    engine = reservations_postgres.engine
    _run_0025_upgrade(engine, reservations_postgres.monkeypatch)

    with engine.connect() as connection:
        constraints, indexes = _unique_objects(connection)
        assert RESERVATION_CONSTRAINT in constraints
        assert RESERVATION_INDEX not in indexes, (
            "the signature guard must not add a unique index the table's own "
            "constraint already covers"
        )
        assert find_equivalent_duplicates(
            sa.inspect(connection), [RESERVATIONS]
        ) == []
        physical = connection.execute(sa.text(
            "select indexname from pg_indexes where schemaname = current_schema() "
            "and tablename = :table and indexdef like '%UNIQUE%' "
            "and indexname != 'material_reservations_pkey'"
        ), {"table": RESERVATIONS}).scalars().all()
        assert set(physical) == {RESERVATION_CONSTRAINT}

    # Uniqueness is still enforced, now by the surviving constraint. Real
    # parent rows are needed because reservation_no's table carries FKs.
    metadata = sa.MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection)

        def insert(table, **values):
            row = metadata.tables[table]
            return connection.execute(
                row.insert().values(**values).returning(row.c.id)
            ).scalar_one()

        model_id = insert("models", code="PRE-GUARD", name="Pre-guard model",
                          status="draft", sam_minutes=0)
        order_id = insert("production_orders", production_no="PRE-GUARD-PO",
                          production_type="branded_stock", model_id=model_id,
                          status="waiting", planned_quantity=1)
        item_id = insert("items", sku="PRE-GUARD-SKU", name="Pre-guard item",
                         category="fabric", unit="pcs", default_cost=1,
                         reorder_level=0, track_batch=False, is_active=True)

        def add_reservation(number):
            connection.execute(sa.text(
                f"INSERT INTO {RESERVATIONS} (reservation_no, production_order_id, "
                "item_id, reserved_quantity, consumed_quantity, released_quantity, unit) "
                "VALUES (:number, :order, :item, 1, 0, 0, 'pcs')"
            ), {"number": number, "order": order_id, "item": item_id})

        add_reservation("PRE-GUARD-1")
        with pytest.raises(sa.exc.IntegrityError):
            add_reservation("PRE-GUARD-1")


def test_postgres_guard_still_creates_the_non_redundant_indexes(reservations_postgres):
    """The guard must not over-suppress: unrelated indexes are still created."""
    engine = reservations_postgres.engine
    _run_0025_upgrade(engine, reservations_postgres.monkeypatch)

    with engine.connect() as connection:
        names = {item["name"] for item in sa.inspect(connection).get_indexes(RESERVATIONS)}
    for expected in (
        "ix_material_reservations_production_order_id",
        "ix_material_reservations_sales_order_id",
        "ix_material_reservations_item_id",
        "ix_material_reservations_stock_batch_id",
        "ix_material_reservations_warehouse_id",
        "ix_material_reservations_status",
    ):
        assert expected in names


def test_postgres_duplicate_audit_does_not_count_a_constraint_against_itself(
    reservations_postgres,
):
    """A PostgreSQL unique constraint is backed by an index of the same name.

    The inspector reports that backing index again; it must not look like a
    second equivalent object or every unique constraint would be a false
    positive.
    """
    engine = reservations_postgres.engine
    _run_0025_upgrade(engine, reservations_postgres.monkeypatch)

    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        backing = [
            item["name"] for item in inspector.get_indexes(RESERVATIONS)
            if item.get("duplicates_constraint")
        ]
        assert backing == [RESERVATION_CONSTRAINT]
        grouped = object_signatures(inspector, RESERVATIONS)
        signature = index_signature(RESERVATIONS, ["reservation_no"], unique=True)
        assert len(grouped[signature]) == 1, "a constraint is one object, not two"
        assert grouped[signature][0]["type"] == "unique_constraint"
