"""Read-only DB06/DB08 catalog evidence. Never executes or approves a migration."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import sqlalchemy as sa  # noqa: E402
from app.migrations.bootstrap_guards import find_equivalent_duplicates  # noqa: E402


def audit(engine, schema: str | None = None) -> dict:
    if engine.dialect.name != "postgresql":
        raise ValueError("Catalog evidence requires PostgreSQL")
    if schema and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("Invalid schema identifier")
    spec = importlib.util.spec_from_file_location(
        "schema_alignment", BACKEND / "alembic/versions/0138_ismail_schema_contract.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            if schema:
                connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            inspector = sa.inspect(connection)
            tables = inspector.get_table_names()
            version = (connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
                       if "alembic_version" in tables else [])
            cleanup = migration.reservation_index_plan(connection)
            cleanup_plans = [
                {"table": table, "redundant": redundant, "covering": covering, "type": "unique_index",
                 "action": migration.unique_index_plan(connection, table, redundant, covering)}
                for table, redundant, covering, _ in migration.UNIQUE_PAIRS
            ] + [
                {"table": table, "redundant": redundant, "covering": covering, "type": "foreign_key",
                 "action": migration.foreign_key_plan(connection, table, redundant, covering)}
                for table, redundant, covering, _, _ in migration.FK_PAIRS
            ]
            index_plans = []
            for table, column in migration.HR_INDEXES:
                indexes = inspector.get_indexes(table)
                name = f"ix_{table}_{column}"
                existing = next((index for index in indexes if index["name"] == name), None)
                options = (existing or {}).get("dialect_options") or {}
                matches = bool(existing and existing["column_names"] == [column]
                               and not existing["unique"] and not any(options.values()))
                index_plans.append({"table": table, "column": column, "name": name,
                                    "action": "create" if not existing else "keep" if matches else "refuse",
                                    "rows": connection.scalar(sa.text(f'SELECT count(*) FROM "{table}"'))})
            duplicates = [item.to_dict() for item in find_equivalent_duplicates(inspector, tables)]
            return {"read_only": True, "executes_migration": False, "database_revision": version,
                    "server_version": connection.scalar(sa.text("SHOW server_version")),
                    "schema": connection.scalar(sa.text("SELECT current_schema()")),
                    "reservation_index": {"name": migration.REDUNDANT, "covering": migration.COVERING,
                                          "action": cleanup},
                    "hr_indexes": index_plans, "verified_cleanup_objects": cleanup_plans,
                    "candidate_duplicates": duplicates,
                    "limits": ["Candidate signatures are evidence for manual review, not permission to drop objects.",
                               "Catalog findings describe only this database, not production.",
                               "Production migration requires exact preflight, backup and owner approval."]}
        finally:
            transaction.rollback()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="STABILIZATION_POSTGRES_URL")
    parser.add_argument("--schema")
    parser.add_argument("--allow-remote", action="store_true")
    args = parser.parse_args()
    raw = os.environ.get(args.database_url_env)
    if not raw:
        parser.error(f"Set {args.database_url_env} to the database URL; it will not be printed")
    url = sa.engine.make_url(raw)
    if url.get_backend_name() != "postgresql":
        parser.error("Only PostgreSQL is supported")
    if url.host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_remote:
        parser.error("Non-loopback catalog reads require --allow-remote")
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool,
                              connect_args={"connect_timeout": 5, "options": "-cstatement_timeout=30000 -clock_timeout=5000"})
    try:
        print(json.dumps(audit(engine, args.schema), indent=2, sort_keys=True))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
