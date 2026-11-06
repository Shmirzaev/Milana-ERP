"""DB06/DB08 forward alignment against the full real migration chain."""
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.tests.test_fresh_migration_bootstrap import postgres_migrations, load_migration  # noqa: F401


def test_forward_catalog_alignment_preserves_rows_and_unique_constraint(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0137_perf34_shipment_indexes")
    migration = load_migration("0138_ismail_schema_contract")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE INDEX ix_hr_calendar_events_employee_id ON hr_calendar_events (employee_id)")
        # Preserve actual business rows, not just empty-table counts.
        connection.exec_driver_sql("INSERT INTO brands (name, is_active) VALUES ('DB08 synthetic brand', true)")
        connection.exec_driver_sql("INSERT INTO collections (name, brand_id, status) SELECT 'DB08 synthetic collection', id, 'draft' FROM brands WHERE name = 'DB08 synthetic brand'")
        before = {table: connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
                  for table in sa.inspect(connection).get_table_names() if table != "alembic_version"}
        assert migration.reservation_index_plan(connection) == "drop_redundant"
    command.upgrade(config, "head")
    path = Path(__file__).resolve().parents[3] / "scripts/schema_audit.py"
    spec = importlib.util.spec_from_file_location("schema_audit", path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    with engine.connect() as connection:
        schema = connection.scalar(sa.text("SELECT current_schema()"))
    evidence = audit.audit(engine, schema)
    assert evidence["read_only"] and not evidence["executes_migration"]
    assert all(index["action"] == "keep" for index in evidence["hr_indexes"])
    assert evidence["candidate_duplicates"] == []
    assert all(obj["action"] == "already_absent" for obj in evidence["verified_cleanup_objects"])
    output = Path(__file__).resolve().parents[3] / "outputs/ismail-completion"
    output.mkdir(parents=True, exist_ok=True)
    (output / "schema-audit.json").write_text(json.dumps(evidence, indent=2), encoding="utf8")
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        assert migration.reservation_index_plan(connection) == "already_absent"
        assert any(key["name"] == migration.COVERING for key in inspector.get_unique_constraints("material_reservations"))
        for table, column in migration.HR_INDEXES:
            assert any(index["name"] == f"ix_{table}_{column}" and index["column_names"] == [column]
                       for index in inspector.get_indexes(table))
        assert all(connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"')) == count
                   for table, count in before.items())
        # Calling the revision twice must be a harmless no-op, including tags.
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    command.downgrade(config, "0137_perf34_shipment_indexes")
    with engine.connect() as connection:
        assert migration.reservation_index_plan(connection) == "drop_redundant"
        assert any(index["name"] == "ix_hr_calendar_events_employee_id"
                   for index in sa.inspect(connection).get_indexes("hr_calendar_events"))
        assert not any(index["name"] == "ix_hr_calendar_events_event_type"
                       for index in sa.inspect(connection).get_indexes("hr_calendar_events"))
    command.upgrade(config, "head")


def test_duplicate_cleanup_refuses_an_index_with_different_meaning(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0137_perf34_shipment_indexes")
    migration = load_migration("0138_ismail_schema_contract")
    with engine.begin() as connection:
        connection.exec_driver_sql(f'DROP INDEX "{migration.REDUNDANT}"')
        connection.exec_driver_sql(f'CREATE UNIQUE INDEX "{migration.REDUNDANT}" ON material_reservations (reservation_no) WHERE status = \'reserved\'')
        with pytest.raises(RuntimeError, match="catalog identity/coverage differs"):
            migration.reservation_index_plan(connection)


def test_duplicate_cleanup_refuses_different_foreign_key_actions(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0137_perf34_shipment_indexes")
    migration = load_migration("0138_ismail_schema_contract")
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE models DROP CONSTRAINT models_brand_id_fkey")
        connection.exec_driver_sql("ALTER TABLE models ADD CONSTRAINT models_brand_id_fkey FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE")
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="catalog identity/actions differ"):
                migration.upgrade()
        assert migration.reservation_index_plan(connection) == "drop_redundant", "all checks must precede every DROP"


def test_live_single_reservation_index_is_attached_without_rebuild(postgres_migrations):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0137_perf34_shipment_indexes")
    migration = load_migration("0138_ismail_schema_contract")
    with engine.begin() as connection:
        connection.exec_driver_sql(f'ALTER TABLE material_reservations DROP CONSTRAINT "{migration.COVERING}"')
        connection.exec_driver_sql("INSERT INTO brands (name, is_active) VALUES ('Single-index migration synthetic brand', true)")
        oid = connection.scalar(sa.text("SELECT to_regclass(:name)::oid"), {"name": migration.REDUNDANT})
        before = {table: connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))
                  for table in sa.inspect(connection).get_table_names() if table != "alembic_version"}
        assert migration.reservation_index_plan(connection) == "attach_existing_unique_index"
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.scalar(sa.text("SELECT to_regclass(:name)::oid"), {"name": migration.COVERING}) == oid
        assert any(key["name"] == migration.COVERING for key in sa.inspect(connection).get_unique_constraints("material_reservations"))
        assert migration.reservation_index_plan(connection) == "already_absent"
        assert all(connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"')) == count for table, count in before.items())
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    command.downgrade(config, "0137_perf34_shipment_indexes")
    with engine.connect() as connection:
        assert migration.reservation_index_plan(connection) == "drop_redundant"
        assert connection.scalar(sa.text("SELECT to_regclass(:name)::oid"), {"name": migration.COVERING}) == oid
    command.upgrade(config, "head")


@pytest.mark.parametrize("definition", [
    "UNIQUE INDEX {name} ON material_reservations (reservation_no) WHERE status = 'reserved'",
    "INDEX {name} ON material_reservations (reservation_no)",
    "UNIQUE INDEX {name} ON material_reservations (id)",
    "UNIQUE INDEX {name} ON material_reservations (reservation_no DESC)",
])
def test_missing_cover_does_not_allow_attaching_an_incompatible_index(postgres_migrations, definition):
    engine, config = postgres_migrations.engine, postgres_migrations.config
    command.upgrade(config, "0137_perf34_shipment_indexes")
    migration = load_migration("0138_ismail_schema_contract")
    with engine.begin() as connection:
        connection.exec_driver_sql(f'ALTER TABLE material_reservations DROP CONSTRAINT "{migration.COVERING}"')
        connection.exec_driver_sql(f'DROP INDEX "{migration.REDUNDANT}"')
        connection.exec_driver_sql("CREATE " + definition.format(name=migration.REDUNDANT))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="catalog identity/coverage differs"):
                migration.upgrade()
        assert not any(index["name"] == "ix_hr_calendar_events_employee_id" for index in sa.inspect(connection).get_indexes("hr_calendar_events"))
        assert any(index["name"] == "ix_branded_planning_orders_order_no" for index in sa.inspect(connection).get_indexes("branded_planning_orders"))
