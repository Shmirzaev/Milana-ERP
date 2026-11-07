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
        _assert_known_drift_baseline(normalized, _known_drift_baseline() + _gate_compatibility_drift(connection))


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


# Compatibility-only storage contract: reviewed additive turnstile history on
# the unchanged a857 application. Keep the shared 94-entry DB08 baseline intact.
# Exact migration hashes, complete storage signatures and the exact ten extra
# Alembic descriptors prevent this supplement from hiding unknown schema drift.
_GATE_COMPATIBILITY_MIGRATIONS = {'0151_gate_enrollment.py': '821334fc3b05c12bc216b6b9ff0d1c43bec944aab29606d6ba035d4dc6e74899',
 '0152_gate_edit_baseline.py': 'daf368aecebf081366141502fa88bdcae26557d60e60868a237479e9fb072a9b',
 '0153_gate_revoke_tombstone.py': '3d0edaf46eeb4b834c66ad96a07429ca95ebe917eb085cca24226f27d01435e3',
 '0155_eco_gate_merge.py': 'b899f4f87086ae2254cf4d86ecd38c72fbc9b6d563de8150827f973d30a29e61'}
_GATE_COMPATIBILITY_STORAGE = {'gate_employee_devices': {'columns': [['employee_id', 'INTEGER', False, None, False, None],
                                       ['factory_code', 'VARCHAR(3)', False, None, False, None],
                                       ['device_id', 'INTEGER', False, None, False, None],
                                       ['external_person_id', 'VARCHAR(64)', False, None, False, None],
                                       ['state', 'VARCHAR(7)', False, None, False, None],
                                       ['desired_revision', 'INTEGER', False, None, False, None],
                                       ['id', 'INTEGER', False, "nextval('gate_employee_devices_id_seq'::regclass)",
                                        True, None]],
                           'primary_key': {'name': 'gate_employee_devices_pkey', 'constrained_columns': ['id']},
                           'foreign_keys': [{'name': 'gate_employee_devices_device_id_factory_code_fkey',
                                             'constrained_columns': ['device_id', 'factory_code'],
                                             'referred_schema': None,
                                             'referred_table': 'attendance_devices',
                                             'referred_columns': ['id', 'factory_code'],
                                             'options': {}},
                                            {'name': 'gate_employee_devices_employee_id_factory_code_fkey',
                                             'constrained_columns': ['employee_id', 'factory_code'],
                                             'referred_schema': None,
                                             'referred_table': 'employees',
                                             'referred_columns': ['id', 'factory_code'],
                                             'options': {}}],
                           'unique_constraints': [{'name': 'uq_gate_binding_device_external',
                                                   'column_names': ['device_id', 'external_person_id']},
                                                  {'name': 'uq_gate_binding_employee_device',
                                                   'column_names': ['employee_id', 'device_id']},
                                                  {'name': 'uq_gate_binding_scope',
                                                   'column_names': ['id', 'employee_id', 'factory_code',
                                                                    'device_id']}],
                           'checks': [{'name': 'ck_gate_binding_revision', 'sqltext': 'desired_revision > 0'},
                                      {'name': 'gate_gatebindingstate',
                                       'sqltext': "state::text = ANY (ARRAY['pending'::character varying, "
                                                  "'active'::character varying, 'revoked'::character "
                                                  'varying]::text[])'}],
                           'indexes': [{'name': 'uq_gate_binding_device_external',
                                        'column_names': ['device_id', 'external_person_id'],
                                        'unique': True,
                                        'dialect_options': {'postgresql_include': []},
                                        'duplicates_constraint': 'uq_gate_binding_device_external'},
                                       {'name': 'uq_gate_binding_employee_device',
                                        'column_names': ['employee_id', 'device_id'],
                                        'unique': True,
                                        'dialect_options': {'postgresql_include': []},
                                        'duplicates_constraint': 'uq_gate_binding_employee_device'},
                                       {'name': 'uq_gate_binding_scope',
                                        'column_names': ['id', 'employee_id', 'factory_code', 'device_id'],
                                        'unique': True,
                                        'dialect_options': {'postgresql_include': []},
                                        'duplicates_constraint': 'uq_gate_binding_scope'}]},
 'gate_operations': {'columns': [['employee_id', 'INTEGER', False, None, False, None],
                                 ['factory_code', 'VARCHAR(3)', False, None, False, None],
                                 ['requested_by', 'INTEGER', False, None, False, None],
                                 ['action', 'VARCHAR(6)', False, None, False, None],
                                 ['mode', 'VARCHAR(9)', False, None, False, None],
                                 ['revision', 'INTEGER', False, None, False, None],
                                 ['full_name', 'VARCHAR(255)', False, None, False, None],
                                 ['photo_asset_id', 'INTEGER', True, None, False, None],
                                 ['external_person_id', 'VARCHAR(64)', False, None, False, None],
                                 ['snapshot_hash', 'VARCHAR(64)', False, None, False, None],
                                 ['created_at', 'TIMESTAMP', False, 'now()', False, True],
                                 ['id', 'INTEGER', False, "nextval('gate_operations_id_seq'::regclass)", True, None]],
                     'primary_key': {'name': 'gate_operations_pkey', 'constrained_columns': ['id']},
                     'foreign_keys': [{'name': 'gate_operations_employee_id_factory_code_fkey',
                                       'constrained_columns': ['employee_id', 'factory_code'],
                                       'referred_schema': None,
                                       'referred_table': 'employees',
                                       'referred_columns': ['id', 'factory_code'],
                                       'options': {}},
                                      {'name': 'gate_operations_photo_asset_id_employee_id_factory_code_fkey',
                                       'constrained_columns': ['photo_asset_id', 'employee_id', 'factory_code'],
                                       'referred_schema': None,
                                       'referred_table': 'gate_photo_assets',
                                       'referred_columns': ['id', 'employee_id', 'factory_code'],
                                       'options': {}},
                                      {'name': 'gate_operations_requested_by_fkey',
                                       'constrained_columns': ['requested_by'],
                                       'referred_schema': None,
                                       'referred_table': 'users',
                                       'referred_columns': ['id'],
                                       'options': {}}],
                     'unique_constraints': [{'name': 'uq_gate_operation_scope',
                                             'column_names': ['id', 'employee_id', 'factory_code', 'revision']}],
                     'checks': [{'name': 'ck_gate_operation_photo_action',
                                 'sqltext': "(action::text = ANY (ARRAY['edit'::character varying, "
                                            "'revoke'::character varying]::text[])) AND photo_asset_id IS NULL OR "
                                            "(action::text = ANY (ARRAY['enroll'::character varying, "
                                            "'photo'::character varying]::text[])) AND photo_asset_id IS NOT NULL"},
                                {'name': 'ck_gate_operation_revision', 'sqltext': 'revision > 0'},
                                {'name': 'gate_gateaction',
                                 'sqltext': "action::text = ANY (ARRAY['enroll'::character varying, 'edit'::character "
                                            "varying, 'photo'::character varying, 'revoke'::character "
                                            'varying]::text[])'},
                                {'name': 'gate_gatemode',
                                 'sqltext': "mode::text = ANY (ARRAY['disabled'::character varying, "
                                            "'simulator'::character varying]::text[])"}],
                     'indexes': [{'name': 'uq_gate_operation_scope',
                                  'column_names': ['id', 'employee_id', 'factory_code', 'revision'],
                                  'unique': True,
                                  'dialect_options': {'postgresql_include': []},
                                  'duplicates_constraint': 'uq_gate_operation_scope'}]},
 'gate_photo_assets': {'columns': [['employee_id', 'INTEGER', False, None, False, None],
                                   ['factory_code', 'VARCHAR(3)', False, None, False, None],
                                   ['created_by', 'INTEGER', False, None, False, None],
                                   ['stored_name', 'VARCHAR(255)', False, None, False, None],
                                   ['sha256', 'VARCHAR(64)', False, None, False, None],
                                   ['width', 'INTEGER', False, None, False, None],
                                   ['height', 'INTEGER', False, None, False, None],
                                   ['content_type', 'VARCHAR(64)', False, None, False, None],
                                   ['validation', 'VARCHAR(19)', False, None, False, None],
                                   ['created_at', 'TIMESTAMP', False, 'now()', False, True],
                                   ['id', 'INTEGER', False, "nextval('gate_photo_assets_id_seq'::regclass)", True,
                                    None]],
                       'primary_key': {'name': 'gate_photo_assets_pkey', 'constrained_columns': ['id']},
                       'foreign_keys': [{'name': 'gate_photo_assets_created_by_fkey',
                                         'constrained_columns': ['created_by'],
                                         'referred_schema': None,
                                         'referred_table': 'users',
                                         'referred_columns': ['id'],
                                         'options': {}},
                                        {'name': 'gate_photo_assets_employee_id_factory_code_fkey',
                                         'constrained_columns': ['employee_id', 'factory_code'],
                                         'referred_schema': None,
                                         'referred_table': 'employees',
                                         'referred_columns': ['id', 'factory_code'],
                                         'options': {}}],
                       'unique_constraints': [{'name': 'gate_photo_assets_stored_name_key',
                                               'column_names': ['stored_name']},
                                              {'name': 'uq_gate_photo_scope',
                                               'column_names': ['id', 'employee_id', 'factory_code']}],
                       'checks': [{'name': 'ck_gate_photo_dimensions', 'sqltext': 'width > 0 AND height > 0'},
                                  {'name': 'gate_gatephotovalidation',
                                   'sqltext': "validation::text = 'technical_validated'::text"}],
                       'indexes': [{'name': 'gate_photo_assets_stored_name_key',
                                    'column_names': ['stored_name'],
                                    'unique': True,
                                    'dialect_options': {'postgresql_include': []},
                                    'duplicates_constraint': 'gate_photo_assets_stored_name_key'},
                                   {'name': 'uq_gate_photo_scope',
                                    'column_names': ['id', 'employee_id', 'factory_code'],
                                    'unique': True,
                                    'dialect_options': {'postgresql_include': []},
                                    'duplicates_constraint': 'uq_gate_photo_scope'}]},
 'gate_simulator_devices': {'columns': [['device_id', 'INTEGER', False, None, False, None],
                                        ['factory_code', 'VARCHAR(3)', False, None, False, None],
                                        ['online', 'BOOLEAN', False, None, False, None],
                                        ['mode', 'VARCHAR(9)', False, None, False, None],
                                        ['id', 'INTEGER', False, "nextval('gate_simulator_devices_id_seq'::regclass)",
                                         True, None]],
                            'primary_key': {'name': 'gate_simulator_devices_pkey', 'constrained_columns': ['id']},
                            'foreign_keys': [{'name': 'gate_simulator_devices_device_id_factory_code_fkey',
                                              'constrained_columns': ['device_id', 'factory_code'],
                                              'referred_schema': None,
                                              'referred_table': 'attendance_devices',
                                              'referred_columns': ['id', 'factory_code'],
                                              'options': {}}],
                            'unique_constraints': [{'name': 'uq_gate_simulator_device',
                                                    'column_names': ['device_id']}],
                            'checks': [{'name': 'gate_gatemode',
                                        'sqltext': "mode::text = ANY (ARRAY['disabled'::character varying, "
                                                   "'simulator'::character varying]::text[])"}],
                            'indexes': [{'name': 'uq_gate_simulator_device',
                                         'column_names': ['device_id'],
                                         'unique': True,
                                         'dialect_options': {'postgresql_include': []},
                                         'duplicates_constraint': 'uq_gate_simulator_device'}]},
 'gate_simulator_people': {'columns': [['binding_id', 'INTEGER', False, None, False, None],
                                       ['external_person_id', 'VARCHAR(64)', False, None, False, None],
                                       ['accepted_payload_hash', 'VARCHAR(64)', False, None, False, None],
                                       ['accepted_revision', 'INTEGER', False, None, False, None],
                                       ['full_name', 'VARCHAR(255)', False, None, False, None],
                                       ['photo_sha256', 'VARCHAR(64)', False, None, False, None],
                                       ['write_count', 'INTEGER', False, None, False, None],
                                       ['id', 'INTEGER', False, "nextval('gate_simulator_people_id_seq'::regclass)",
                                        True, None],
                                       ['present', 'BOOLEAN', False, 'true', False, None]],
                           'primary_key': {'name': 'gate_simulator_people_pkey', 'constrained_columns': ['id']},
                           'foreign_keys': [{'name': 'gate_simulator_people_binding_id_fkey',
                                             'constrained_columns': ['binding_id'],
                                             'referred_schema': None,
                                             'referred_table': 'gate_employee_devices',
                                             'referred_columns': ['id'],
                                             'options': {}}],
                           'unique_constraints': [{'name': 'gate_simulator_people_binding_id_key',
                                                   'column_names': ['binding_id']}],
                           'checks': [{'name': 'ck_gate_simulator_person_counters',
                                       'sqltext': 'accepted_revision > 0 AND write_count > 0'}],
                           'indexes': [{'name': 'gate_simulator_people_binding_id_key',
                                        'column_names': ['binding_id'],
                                        'unique': True,
                                        'dialect_options': {'postgresql_include': []},
                                        'duplicates_constraint': 'gate_simulator_people_binding_id_key'}]},
 'gate_targets': {'columns': [['operation_id', 'INTEGER', False, None, False, None],
                              ['binding_id', 'INTEGER', False, None, False, None],
                              ['device_id', 'INTEGER', False, None, False, None],
                              ['device_name', 'VARCHAR(255)', False, None, False, None],
                              ['factory_code', 'VARCHAR(3)', False, None, False, None],
                              ['employee_id', 'INTEGER', False, None, False, None],
                              ['revision', 'INTEGER', False, None, False, None],
                              ['state', 'VARCHAR(10)', False, None, False, None],
                              ['attempts', 'INTEGER', False, None, False, None],
                              ['error_code', 'VARCHAR(17)', True, None, False, None],
                              ['lease_token', 'VARCHAR(64)', True, None, False, None],
                              ['lease_expires_at', 'TIMESTAMP', True, None, False, True],
                              ['observed_evidence', 'JSON', True, None, False, None],
                              ['id', 'INTEGER', False, "nextval('gate_targets_id_seq'::regclass)", True, None],
                              ['baseline_revision', 'INTEGER', True, None, False, None],
                              ['baseline_payload_hash', 'VARCHAR(64)', True, None, False, None],
                              ['baseline_full_name', 'VARCHAR(255)', True, None, False, None],
                              ['baseline_external_person_id', 'VARCHAR(64)', True, None, False, None],
                              ['baseline_photo_sha256', 'VARCHAR(64)', True, None, False, None],
                              ['baseline_profile_hash', 'VARCHAR(64)', True, None, False, None],
                              ['desired_payload_hash', 'VARCHAR(64)', True, None, False, None]],
                  'primary_key': {'name': 'gate_targets_pkey', 'constrained_columns': ['id']},
                  'foreign_keys': [{'name': 'gate_targets_binding_id_employee_id_factory_code_device_id_fkey',
                                    'constrained_columns': ['binding_id', 'employee_id', 'factory_code', 'device_id'],
                                    'referred_schema': None,
                                    'referred_table': 'gate_employee_devices',
                                    'referred_columns': ['id', 'employee_id', 'factory_code', 'device_id'],
                                    'options': {}},
                                   {'name': 'gate_targets_operation_id_employee_id_factory_code_revisio_fkey',
                                    'constrained_columns': ['operation_id', 'employee_id', 'factory_code', 'revision'],
                                    'referred_schema': None,
                                    'referred_table': 'gate_operations',
                                    'referred_columns': ['id', 'employee_id', 'factory_code', 'revision'],
                                    'options': {}}],
                  'unique_constraints': [{'name': 'uq_gate_target_operation_device',
                                          'column_names': ['operation_id', 'device_id']}],
                  'checks': [{'name': 'ck_gate_target_counters', 'sqltext': 'revision > 0 AND attempts >= 0'},
                             {'name': 'ck_gate_target_edit_baseline',
                              'sqltext': 'baseline_revision IS NULL AND baseline_payload_hash IS NULL AND '
                                         'baseline_full_name IS NULL AND baseline_external_person_id IS NULL AND '
                                         'baseline_photo_sha256 IS NULL AND baseline_profile_hash IS NULL AND '
                                         'desired_payload_hash IS NULL OR baseline_revision IS NOT NULL AND '
                                         'baseline_revision > 0 AND baseline_payload_hash IS NOT NULL AND '
                                         'length(baseline_payload_hash::text) = 64 AND baseline_full_name IS NOT NULL '
                                         'AND baseline_external_person_id IS NOT NULL AND baseline_photo_sha256 IS '
                                         'NOT NULL AND length(baseline_photo_sha256::text) = 64 AND '
                                         'baseline_profile_hash IS NOT NULL AND length(baseline_profile_hash::text) = '
                                         '64 AND desired_payload_hash IS NOT NULL AND '
                                         'length(desired_payload_hash::text) = 64'},
                             {'name': 'gate_gateerrorcode',
                              'sqltext': "error_code::text = ANY (ARRAY['device_offline'::character varying, "
                                         "'identity_conflict'::character varying, 'payload_conflict'::character "
                                         "varying, 'stale_revision'::character varying, 'lease_expired'::character "
                                         "varying, 'simulator_error'::character varying]::text[])"},
                             {'name': 'gate_gatetargetstate',
                              'sqltext': "state::text = ANY (ARRAY['queued'::character varying, "
                                         "'processing'::character varying, 'verifying'::character varying, "
                                         "'succeeded'::character varying, 'waiting'::character varying, "
                                         "'failed'::character varying, 'conflict'::character varying, "
                                         "'uncertain'::character varying, 'cancelled'::character varying, "
                                         "'superseded'::character varying]::text[])"}],
                  'indexes': [{'name': 'ix_gate_targets_operation_id',
                               'column_names': ['operation_id'],
                               'unique': False,
                               'dialect_options': {'postgresql_include': []}},
                              {'name': 'ix_gate_targets_state',
                               'column_names': ['state'],
                               'unique': False,
                               'dialect_options': {'postgresql_include': []}},
                              {'name': 'uq_gate_target_operation_device',
                               'column_names': ['operation_id', 'device_id'],
                               'unique': True,
                               'dialect_options': {'postgresql_include': []},
                               'duplicates_constraint': 'uq_gate_target_operation_device'}]}}
_GATE_COMPATIBILITY_DIFFS = [['remove_table', 'gate_simulator_people'], ['remove_table', 'gate_simulator_devices'],
 ['remove_table', 'gate_operations'],
 ['remove_index',
  {'expressions': ['gate_targets.operation_id'],
   'index': 'ix_gate_targets_operation_id',
   'options': {},
   'table': 'gate_targets',
   'unique': False}],
 ['remove_index',
  {'expressions': ['gate_targets.state'],
   'index': 'ix_gate_targets_state',
   'options': {},
   'table': 'gate_targets',
   'unique': False}],
 ['remove_table', 'gate_targets'], ['remove_table', 'gate_photo_assets'], ['remove_table', 'gate_employee_devices'],
 ['remove_constraint',
  {'columns': ['id', 'factory_code'],
   'constraint': 'UniqueConstraint',
   'name': 'uq_attendance_devices_id_factory',
   'table': 'attendance_devices'}],
 ['remove_constraint',
  {'columns': ['id', 'factory_code'],
   'constraint': 'UniqueConstraint',
   'name': 'uq_employees_id_factory',
   'table': 'employees'}]]


def _gate_compatibility_drift(connection):
    from app.db.base import Base

    tables = set(_GATE_COMPATIBILITY_STORAGE)
    if tables <= set(Base.metadata.tables):
        return []  # The actual gate application owns these mapped tables.
    assert not tables.intersection(Base.metadata.tables), "Partial gate mapping needs separate contract review"
    assert MigrationContext.configure(connection).get_current_heads() == ("0155_eco_gate_merge",)
    for filename, expected_hash in _GATE_COMPATIBILITY_MIGRATIONS.items():
        assert hashlib.sha256((VERSIONS / filename).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == expected_hash
    inspector = sa.inspect(connection)
    assert {name for name in inspector.get_table_names() if name.startswith("gate_")} == tables
    actual = {}
    for table in sorted(tables):
        primary = inspector.get_pk_constraint(table)
        actual[table] = {
            "columns": [[column["name"], str(column["type"]), column["nullable"], column["default"],
                         column.get("autoincrement", False), getattr(column["type"], "timezone", None)]
                        for column in inspector.get_columns(table)],
            "primary_key": {key: primary[key] for key in ("name", "constrained_columns")},
            "foreign_keys": [{key: constraint[key] for key in ("name", "constrained_columns", "referred_schema",
                "referred_table", "referred_columns", "options")} for constraint in sorted(
                    inspector.get_foreign_keys(table), key=lambda item: item["name"])],
            "unique_constraints": [{key: constraint[key] for key in ("name", "column_names")} for constraint in sorted(
                inspector.get_unique_constraints(table), key=lambda item: item["name"])],
            "checks": [{key: constraint[key] for key in ("name", "sqltext")} for constraint in sorted(
                inspector.get_check_constraints(table), key=lambda item: item["name"])],
            "indexes": [{key: index[key] for key in ("name", "column_names", "unique", "dialect_options",
                "duplicates_constraint") if key in index} for index in sorted(
                    inspector.get_indexes(table), key=lambda item: item["name"])],
        }
    assert actual == _GATE_COMPATIBILITY_STORAGE, "Gate compatibility storage contract changed"
    for table, name in (("employees", "uq_employees_id_factory"),
                        ("attendance_devices", "uq_attendance_devices_id_factory")):
        constraints = inspector.get_unique_constraints(table)
        assert [{"name": row["name"], "column_names": row["column_names"]} for row in constraints
                if row["name"] == name] == [{"name": name, "column_names": ["id", "factory_code"]}]
    return _GATE_COMPATIBILITY_DIFFS


@pytest.mark.parametrize("change", ["missing_column", "missing_index", "extra_column", "missing_check", "timezone"])
def test_postgres_gate_compatibility_contract_rejects_storage_drift(postgres_migrations, change):
    from app.db.base import Base

    if set(_GATE_COMPATIBILITY_STORAGE) <= set(Base.metadata.tables):
        pytest.skip("Unmapped old-application schema-0155 compatibility candidate only")
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert _gate_compatibility_drift(connection) == _GATE_COMPATIBILITY_DIFFS
        statements = {
            "missing_column": "ALTER TABLE gate_simulator_people DROP COLUMN present",
            "missing_index": "DROP INDEX ix_gate_targets_state",
            "extra_column": "ALTER TABLE gate_simulator_people ADD COLUMN unreviewed INTEGER",
            "missing_check": "ALTER TABLE gate_operations DROP CONSTRAINT ck_gate_operation_photo_action",
            "timezone": "ALTER TABLE gate_targets ALTER COLUMN lease_expires_at TYPE timestamp without time zone",
        }
        connection.exec_driver_sql(statements[change])
        with pytest.raises(AssertionError, match="Gate compatibility storage contract changed"):
            _gate_compatibility_drift(connection)
