"""Read-only migration impact preflight (tracker DB05).

Prints the exact impact a migration revision *would* have on a database without
executing it. The preview is predecessor-gated and runs inside a
``SET TRANSACTION READ ONLY`` transaction that is always rolled back, so this
command can never re-run a destructive or grant migration.

Examples:
    python scripts/migration_preflight.py --list
    python scripts/migration_preflight.py 0055_delete_mistaken_po15 \\
        --database-url postgresql+psycopg2://user@127.0.0.1:5432/postgres
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import sqlalchemy as sa  # noqa: E402

from app.migrations import preflight  # noqa: E402

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _lineage_rows(script) -> list[dict]:
    rows = []
    for revision in script.walk_revisions():
        rows.append({
            "revision": revision.revision,
            "down_revisions": list(preflight._down_revisions(revision)),
            "summary": (revision.doc or "").strip().splitlines()[0] if revision.doc else None,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("revision", nargs="?", help="Revision id to preview")
    parser.add_argument("--database-url", help="PostgreSQL URL to preview against")
    parser.add_argument("--list", action="store_true", help="List this branch's lineage")
    parser.add_argument("--allow-remote", action="store_true",
                        help="Permit a non-loopback database URL")
    args = parser.parse_args()

    script = preflight.resolve_script_directory()

    if args.list or not args.revision:
        print(json.dumps({
            "heads": sorted(script.get_heads()),
            "revisions": _lineage_rows(script),
        }, indent=2, sort_keys=True))
        return 0

    if not args.database_url:
        parser.error("--database-url is required to preview a revision")

    parsed = urlsplit(args.database_url)
    if parsed.scheme.split("+")[0] != "postgresql":
        raise SystemExit(f"Only PostgreSQL is supported, got {parsed.scheme!r}")
    if parsed.hostname not in LOOPBACK_HOSTS and not args.allow_remote:
        raise SystemExit(
            f"Refusing non-loopback host {parsed.hostname!r} without --allow-remote"
        )

    # Never fall back to ambient application credentials.
    engine = sa.create_engine(args.database_url, poolclass=sa.pool.NullPool, future=True)
    try:
        report = preflight.preview_revision(engine, args.revision, script=script)
    except preflight.PreflightError as error:
        print(json.dumps({
            "revision": args.revision,
            "refused": True,
            "reason": str(error),
            "executes_migration": False,
        }, indent=2, sort_keys=True))
        return 2
    finally:
        engine.dispose()

    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
