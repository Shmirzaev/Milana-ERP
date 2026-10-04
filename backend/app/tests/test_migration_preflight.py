"""DB05: the migration preflight must be read-only and predecessor-gated.

``0055_delete_mistaken_po15`` is the destructive migration this row is named
for. It is already self-guarding in PostgreSQL (``RAISE NOTICE`` when the PO is
absent, ``RAISE EXCEPTION`` when production activity now exists), so the missing
piece is the preview tooling. These tests pin the three properties the row
requires of that tooling:

* it cannot write - every statement is validated and the transaction is
  ``READ ONLY`` at the PostgreSQL level, and the module has no path that runs a
  migration;
* it is gated on the revision the target actually applies to;
* it reports the exact rows, from read-only queries, and refuses rather than
  guessing when it cannot resolve impact exactly.

PostgreSQL coverage is opt-in through ``STABILIZATION_POSTGRES_URL``; the
static and parsing tests run everywhere.
"""

import ast
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[2]
MIGRATIONS = BACKEND / "app" / "migrations"

from app.migrations import preflight  # noqa: E402

TARGET = "0055_delete_mistaken_po15"
PREDECESSOR = "0054_payroll_qr_ids"


@pytest.fixture(scope="module")
def script():
    """This branch's real lineage, resolved from disk at call time."""
    return preflight.resolve_script_directory()


@pytest.fixture(scope="module")
def target_sql():
    return (BACKEND / "alembic" / "versions" / f"{TARGET}.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# read-only, structurally
# --------------------------------------------------------------------------- #

def test_preflight_has_no_path_that_runs_a_migration():
    """The module must not be able to re-run a destructive or grant migration.

    Checked against the parsed import graph rather than the raw text, so prose in
    a docstring cannot satisfy or break the assertion.
    """
    source = (MIGRATIONS / "preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
    assert "alembic.command" not in imported
    assert "alembic.op" not in imported
    assert "alembic" not in imported or not any(
        name.endswith(".op") for name in imported
    )
    # No module-level reference to the Alembic operation proxy.
    assert not any(
        isinstance(node, ast.Name) and node.id == "op" for node in ast.walk(tree)
    )
    assert not hasattr(preflight, "upgrade")
    assert not hasattr(preflight, "command")


@pytest.mark.parametrize("statement", [
    "DELETE FROM work_orders WHERE id = 1",
    "UPDATE work_orders SET status = 'x'",
    "INSERT INTO work_orders (id) VALUES (1)",
    "DROP TABLE work_orders",
    "CREATE INDEX ix ON work_orders (id)",
    "GRANT SELECT ON work_orders TO erp",
    "TRUNCATE work_orders",
    "DO $$ BEGIN DELETE FROM work_orders; END $$",
    "SELECT 1; DROP TABLE work_orders",
    "VACUUM work_orders",
])
def test_validate_read_only_refuses_every_mutating_statement(statement):
    with pytest.raises(preflight.PreflightRefused):
        preflight._validate_read_only(statement)


@pytest.mark.parametrize("statement", [
    "SELECT count(*) FROM work_orders",
    "select count(*) from work_orders where id = 1",
    "WITH target AS (SELECT id FROM production_orders) SELECT count(*) FROM target",
])
def test_validate_read_only_accepts_read_statements(statement):
    assert preflight._validate_read_only(statement) == " ".join(statement.split())


def test_reported_preview_never_claims_to_execute():
    report_block = preflight._approval_block()
    assert report_block["executes_migration"] is False
    assert report_block["read_only"] is True
    assert report_block["requires_postgresql_backup"] is True
    assert report_block["requires_owner_approval"] is True


# --------------------------------------------------------------------------- #
# lineage: adapted to this branch, not assumed
# --------------------------------------------------------------------------- #

def test_lineage_resolves_this_branch_head(script):
    assert sorted(script.get_heads()) == ["0136_employee_salary_precision"]


def test_target_predecessor_comes_from_this_branch(script):
    described = preflight.describe_lineage(script, TARGET)
    assert described["down_revisions"] == [PREDECESSOR]
    assert described["summary"] == "delete mistaken production workflow PO-2026-000015"


def test_predecessor_gate_passes_only_at_the_real_predecessor(script):
    gate = preflight.predecessor_gate(script, TARGET, PREDECESSOR)
    assert gate["passed"] is True
    assert gate["database_revision"] == PREDECESSOR


@pytest.mark.parametrize("database_revision", [
    None,
    "0001_initial",
    "0136_employee_salary_precision",
    "0053_payroll_qr_control",
])
def test_predecessor_gate_refuses_any_other_revision(script, database_revision):
    with pytest.raises(preflight.PreflightRefused, match="Predecessor gate refused|not Alembic-stamped"):
        preflight.predecessor_gate(script, TARGET, database_revision)


def test_predecessor_gate_refuses_a_head_revision(script):
    """A preview taken at head says nothing about 0055, which is long applied."""
    with pytest.raises(preflight.PreflightRefused):
        preflight.predecessor_gate(script, TARGET, script.get_current_head())


# --------------------------------------------------------------------------- #
# classification and exact-impact parsing
# --------------------------------------------------------------------------- #

def test_classify_source_flags_0055_as_destructive(target_sql):
    classification = preflight.classify_source(target_sql)
    assert classification["destructive"] is True
    assert classification["permission"] is False
    assert classification["previews_statically"] is True
    assert classification["dynamic_sql_payloads"] == []


def test_classify_source_flags_a_grant_migration():
    source = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.execute(\"GRANT SELECT ON work_orders TO erp\")\n"
    )
    assert preflight.classify_source(source)["permission"] is True


def test_classify_source_reports_dynamic_sql_instead_of_guessing():
    source = (
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.execute(f\"DELETE FROM {table}\")\n"
    )
    classification = preflight.classify_source(source)
    assert classification["previews_statically"] is False
    assert classification["dynamic_sql_payloads"] == ["execute:JoinedStr"]


def test_analysis_resolves_every_delete_in_0055_exactly(target_sql):
    payload = next(sql for _, sql in preflight._execute_payloads(target_sql) if sql)
    analysis = preflight.analyze_destructive_block(payload)

    assert [delete["table"] for delete in analysis["deletes"]] == [
        "work_orders", "production_order_items", "production_orders",
    ]
    subquery = "(SELECT id FROM production_orders WHERE production_no = 'PO-2026-000015')"
    for delete in analysis["deletes"]:
        assert subquery in delete["where"]
        assert delete["count_sql"].startswith("SELECT count(*) FROM ")
    assert analysis["deletes"][2]["where"] == f"id = {subquery}"


def test_analysis_strips_locking_clause_that_a_read_only_preview_cannot_run(target_sql):
    """``FOR UPDATE`` is rejected by PostgreSQL inside a READ ONLY transaction."""
    payload = next(sql for _, sql in preflight._execute_payloads(target_sql) if sql)
    analysis = preflight.analyze_destructive_block(payload)
    resolutions = analysis["scalar_resolutions"]
    assert "FOR UPDATE" in payload.upper()
    assert "FOR UPDATE" not in str(resolutions).upper()
    # The variable survives only as the dict key; every *value* is resolved SQL.
    assert list(resolutions) == ["target_id"]
    assert "target_id" not in " ".join(resolutions.values())
    assert analysis["returns_early"] is True


def test_analysis_reports_both_self_guards_of_0055(target_sql):
    payload = next(sql for _, sql in preflight._execute_payloads(target_sql) if sql)
    conditions = preflight.analyze_destructive_block(payload)["conditions"]
    assert [item["raise_level"] for item in conditions] == ["NOTICE", "EXCEPTION"]
    assert conditions[0]["returns_early"] is True
    assert conditions[1]["returns_early"] is False
    assert conditions[1]["raise_message"].startswith("Refusing to delete PO-2026-000015")


@pytest.mark.parametrize("payload, reason", [
    ("DO $$\nBEGIN\n    DELETE FROM work_orders;\nEND $$;", "unbounded delete"),
    ("DO $$\nDECLARE\n    target_id INTEGER;\nBEGIN\n    DELETE FROM work_orders WHERE id = target_id;\nEND $$;",
     "declared but never assigned"),
    ("DO $$\nBEGIN\n    DELETE FROM work_orders WHERE id = 1;\n    TRUNCATE audit_logs;\nEND $$;",
     "Unresolvable statement"),
])
def test_analysis_refuses_instead_of_guessing(payload, reason):
    with pytest.raises(preflight.PreflightUnsupported, match=reason):
        preflight.analyze_destructive_block(payload)


def test_substitute_identifiers_does_not_touch_string_literals():
    out = preflight.substitute_identifiers(
        "production_no = 'target_id' AND production_order_id = target_id",
        {"target_id": "(SELECT 1)"},
    )
    assert "'target_id'" in out
    assert "production_order_id = (SELECT 1)" in out


def test_substitute_identifiers_respects_identifier_boundaries():
    out = preflight.substitute_identifiers("target_id2 = target_id", {"target_id": "(SELECT 1)"})
    assert out == "target_id2 = (SELECT 1)"


# --------------------------------------------------------------------------- #
# PostgreSQL: exact impact, and the read-only guarantee at the database level
# --------------------------------------------------------------------------- #

@pytest.fixture
def destructive_postgres(monkeypatch):
    """A disposable loopback PostgreSQL schema migrated to 0054's state."""
    raw_url = os.environ.get("STABILIZATION_POSTGRES_URL")
    if not raw_url:
        pytest.skip("Set STABILIZATION_POSTGRES_URL for disposable PostgreSQL migration coverage")
    url = sa.engine.make_url(raw_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Preflight tests require a loopback PostgreSQL URL")
    schema = f"preflight_{uuid4().hex}"
    engine = sa.create_engine(
        url, poolclass=sa.pool.NullPool,
        connect_args={"options": f"-csearch_path={schema}"},
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    try:
        from alembic import command
        from alembic.config import Config

        from app.core.config import settings

        monkeypatch.setattr(settings, "DATABASE_URL", url.render_as_string(hide_password=False))
        monkeypatch.setattr(sa, "engine_from_config", lambda *args, **kwargs: engine)
        config = Config(str(BACKEND / "alembic.ini"))
        command.upgrade(config, PREDECESSOR)
        yield SimpleNamespace(engine=engine, config=config)
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()


def _seed_po(engine, *, production_no="PO-2026-000015", work_orders=2, active=False):
    """Insert a synthetic PO-2026-000015 exactly as 0055 expects to find it."""
    metadata = sa.MetaData()
    with engine.begin() as connection:
        metadata.reflect(connection)

        def insert(table, **values):
            row = metadata.tables[table]
            return connection.execute(
                row.insert().values(**values).returning(row.c.id)
            ).scalar_one()

        department_id = insert("departments", name="Preflight department", code="PRE-FLT")
        model_id = insert("models", code="PRE-FLT", name="Preflight model",
                          status="draft", sam_minutes=0)
        order_id = insert("production_orders", production_no=production_no,
                          production_type="branded_stock", model_id=model_id,
                          status="waiting", planned_quantity=2)
        insert("production_order_items", production_order_id=order_id, model_id=model_id,
               color="Black", size="M", planned_quantity=2, completed_quantity=0,
               printing_required=False)
        for index in range(work_orders):
            insert("work_orders", production_order_id=order_id, department_id=department_id,
                   operation=f"op-{index}", status="waiting", planned_input_qty=2,
                   planned_output_qty=2, actual_input_qty=0, actual_output_qty=0,
                   passed_qty=0, failed_qty=0, rework_qty=0, is_blocked=False)
        if active:
            connection.execute(
                sa.text("UPDATE work_orders SET actual_output_qty = 5 WHERE production_order_id = :p"),
                {"p": order_id},
            )
        return order_id


def test_postgres_read_only_transaction_rejects_a_write(destructive_postgres):
    """The read-only guarantee is enforced by PostgreSQL, not by convention."""
    engine = destructive_postgres.engine
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        assert connection.execute(sa.text("SELECT 1")).scalar() == 1
        with pytest.raises(sa.exc.DatabaseError):
            connection.execute(sa.text("UPDATE departments SET name = 'x' WHERE false"))
    finally:
        transaction.rollback()
        connection.close()


def test_postgres_preview_reports_exact_impact_and_deletes_nothing(destructive_postgres, script):
    engine = destructive_postgres.engine
    _seed_po(engine)

    report = preflight.preview_revision(engine, TARGET, script=script)

    assert report.gate["passed"] is True
    assert report.gate["database_revision"] == PREDECESSOR
    assert report.classification["destructive"] is True
    assert report.exact_impact["outcome"] == "delete"
    assert report.exact_impact["total_rows_deleted"] == 4
    counts = {delete["table"]: delete["rows"] for delete in report.exact_impact["deletes"]}
    assert counts == {"work_orders": 2, "production_order_items": 1, "production_orders": 1}
    assert report.safety["executes_migration"] is False

    # The preview must leave every row exactly where it was.
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM production_orders")).scalar() == 1
        assert connection.execute(sa.text("SELECT count(*) FROM work_orders")).scalar() == 2
        assert connection.execute(
            sa.text("SELECT count(*) FROM production_order_items")
        ).scalar() == 1
        assert preflight.current_revision(connection) == PREDECESSOR


def test_postgres_preview_reports_refusal_when_production_activity_exists(
    destructive_postgres, script
):
    engine = destructive_postgres.engine
    _seed_po(engine, active=True)

    report = preflight.preview_revision(engine, TARGET, script=script)

    assert report.exact_impact["would_raise_exception"] is True
    assert report.exact_impact["outcome"] == "refuse"
    assert report.exact_impact["total_rows_deleted"] == 0
    assert report.exact_impact["refusal_message"] == (
        "Refusing to delete PO-2026-000015 because production activity now exists"
    )
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT count(*) FROM work_orders")).scalar() == 2


def test_postgres_preview_is_a_no_op_when_the_po_is_absent(destructive_postgres, script):
    engine = destructive_postgres.engine
    report = preflight.preview_revision(engine, TARGET, script=script)

    assert report.exact_impact["would_no_op"] is True
    assert report.exact_impact["outcome"] == "no_op"
    assert report.exact_impact["total_rows_deleted"] == 0


def test_postgres_preview_is_predecessor_gated(destructive_postgres, script):
    """After head, 0055 is applied; a preview there must be refused, not guessed."""
    from alembic import command

    engine = destructive_postgres.engine
    _seed_po(engine)
    command.upgrade(destructive_postgres.config, "0056_payroll_qr_sewing_line")

    with pytest.raises(preflight.PreflightRefused, match="Predecessor gate refused"):
        preflight.preview_revision(engine, TARGET, script=script)
