"""Rehearse the ECO/turnstile merge on newly created local PostgreSQL databases.

Run from any directory with MIGRATION_REHEARSAL_ADMIN_URL set to a loopback
PostgreSQL admin connection. Existing databases are never migrated or dropped.
Each scenario creates its own random database and removes only that database.
Use --graph-only for the dependency graph check without a running PostgreSQL.
This is a disposable rehearsal, never a production downgrade procedure.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import uuid

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
MERGE = "0155_eco_gate_merge"
PREDECESSORS = ("0154_eco_receipt_details", "0153_gate_revoke_tombstone")
ECO_TABLES = {
    "eco_material_batches", "eco_material_movements", "factory_fabric_transfers",
    "factory_fabric_transfer_lines", "eco_accessory_plans",
    "eco_accessory_requirements", "eco_accessory_allocations",
}
GATE_TABLES = {
    "gate_photo_assets", "gate_employee_devices", "gate_operations", "gate_targets",
    "gate_simulator_devices", "gate_simulator_people",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def check_graph():
    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    require(scripts.get_heads() == [MERGE], "Expected exactly the reconciled head")
    revision = scripts.get_revision(MERGE)
    require(tuple(revision.down_revision) == PREDECESSORS, "Wrong merge parents")
    for predecessor in PREDECESSORS:
        pending = list(scripts.iterate_revisions(MERGE, predecessor))
        require(pending[0].revision == MERGE, "Merge is not the final upgrade")
    print(f"PASS graph: one head {MERGE}; both histories reachable", flush=True)


def migrate(url, action, target):
    env = dict(os.environ)
    env.update(DATABASE_URL=url.render_as_string(hide_password=False), ENV="test")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, target], cwd=BACKEND,
        env=env, capture_output=True, text=True, timeout=180,
    )
    # Print migration names only on success; do not expose connection strings
    # or inherited environment values if a driver or application import fails.
    if result.returncode:
        diagnostic = result.stdout + result.stderr
        diagnostic = diagnostic.replace(url.render_as_string(hide_password=False), "<local-db>")
        if url.password:
            diagnostic = diagnostic.replace(url.password, "<redacted>")
        raise RuntimeError(f"Alembic {action} {target} failed:\n{diagnostic}")


def snapshot(connection, names=None):
    actual = inspect(connection)
    names = names or (set(actual.get_table_names()) - {"alembic_version"})
    quote = connection.dialect.identifier_preparer.quote
    return {
        name: (
            connection.execute(text("SELECT to_regclass(:name)::oid"), {"name": name}).scalar_one(),
            connection.execute(text(
                f"SELECT row_to_json(t)::text FROM public.{quote(name)} t ORDER BY 1"
            )).scalars().all(),
        )
        for name in names
    }


def seed_disposable_evidence(connection, predecessor):
    user_id = connection.execute(text(
        "INSERT INTO users (name,email,password_hash,is_active) "
        "VALUES ('Migration rehearsal','merge-rehearsal@example.invalid','disabled',false) RETURNING id"
    )).scalar_one()
    connection.execute(text(
        "INSERT INTO employees (full_name,status,factory_code,salary) "
        "VALUES ('Migration rehearsal','active','MIL',1234.56)"
    ))
    if predecessor == "0154_eco_receipt_details":
        item_id = connection.execute(text(
            "INSERT INTO items (sku,name,category,unit,default_cost,reorder_level,track_batch,is_active) "
            "VALUES ('MERGE-REHEARSAL','Merge rehearsal','fabric','kg',12.34,0,true,true) RETURNING id"
        )).scalar_one()
        connection.execute(text(
            "INSERT INTO eco_material_batches "
            "(item_id,kind,batch_no,unit,quantity,reserved_quantity,created_by,receipt_details) "
            "VALUES (:item,'fabric','MERGE-REHEARSAL','kg',123.4567,12.3456,:actor,"
            "'{\"rehearsal\":\"preserve-receipt\"}'::json)"
        ), {"item": item_id, "actor": user_id})
    else:
        employee_id = connection.execute(text(
            "SELECT id FROM employees WHERE full_name = 'Migration rehearsal'"
        )).scalar_one()
        connection.execute(text(
            "INSERT INTO gate_operations (employee_id,factory_code,requested_by,action,mode,revision,"
            "full_name,photo_asset_id,external_person_id,snapshot_hash) "
            "VALUES (:employee,'MIL',:actor,'revoke','simulator',1,'Migration rehearsal',NULL,"
            "'rehearsal-person',:hash)"
        ), {"employee": employee_id, "actor": user_id, "hash": "a" * 64})


def check_final(connection):
    actual = inspect(connection)
    tables = set(actual.get_table_names())
    require(ECO_TABLES | GATE_TABLES <= tables, "A preserved branch is missing tables")
    require(connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [MERGE],
            "Database did not reach the single merge head")
    for table in ("eco_material_batches", "factory_fabric_transfer_lines"):
        require("receipt_details" in {c["name"] for c in actual.get_columns(table)},
                "ECO receipt details missing")
    require("present" in {c["name"] for c in actual.get_columns("gate_simulator_people")},
            "Turnstile tombstone missing")
    require("baseline_revision" in {c["name"] for c in actual.get_columns("gate_targets")},
            "Turnstile edit baseline missing")
    require(connection.execute(text(
        "SELECT count(*) FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace "
        "WHERE n.nspname='public' AND NOT i.indisvalid"
    )).scalar_one() == 0, "Invalid index after migration")


def rehearse(admin_url, predecessor):
    database = "milana_merge_rehearsal_" + uuid.uuid4().hex
    url = admin_url.set(database=database)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
            created = True
        engine = create_engine(url)
        before = None
        if predecessor:
            migrate(url, "upgrade", predecessor)
            with engine.begin() as connection:
                require(connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
                        == [predecessor], "Predecessor setup did not reach its exact head")
                seed_disposable_evidence(connection, predecessor)
                before = snapshot(connection)
        migrate(url, "upgrade", "head")
        with engine.connect() as connection:
            check_final(connection)
            if before is not None:
                require(snapshot(connection, before.keys()) == before,
                        "Upgrade changed existing table identities or business rows")
            after = snapshot(connection)
        # Unmerge only: both parent heads remain applied. No branch DDL is undone.
        migrate(url, "downgrade", PREDECESSORS[0])
        with engine.connect() as connection:
            require(set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
                    == set(PREDECESSORS), "Unmerge did not retain both parent heads")
            require(snapshot(connection) == after, "Unmerge changed business tables/rows")
        migrate(url, "upgrade", "head")
        with engine.connect() as connection:
            check_final(connection)
            require(snapshot(connection) == after, "Re-upgrade changed business tables/rows")
        print(f"PASS {predecessor or 'fresh'}: upgrade, preserved rows/OIDs, unmerge and re-upgrade", flush=True)
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{database}"'))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-only", action="store_true")
    args = parser.parse_args()
    check_graph()
    if args.graph_only:
        return
    raw = os.environ.get("MIGRATION_REHEARSAL_ADMIN_URL")
    require(raw, "Set MIGRATION_REHEARSAL_ADMIN_URL to an owned local PostgreSQL admin connection")
    url = make_url(raw)
    require(url.get_backend_name() == "postgresql"
            and url.host in {"localhost", "127.0.0.1", "::1"} and not url.query,
            "Rehearsal permits only loopback PostgreSQL without connection overrides")
    for predecessor in (None, *PREDECESSORS):
        rehearse(url, predecessor)


if __name__ == "__main__":
    main()
