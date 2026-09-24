"""Read-only preflight for data-affecting migrations.

Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted connection URL and run:
    python scripts/migration_preflight.py --revision 0130
    python scripts/migration_preflight.py --revision 0055
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.migrations.preflight import read_only_preflight_0055, read_only_preflight_0130  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only migration impact preview")
    parser.add_argument("--revision", choices=("0055", "0130"), default="0130")
    args = parser.parse_args()
    database_url = os.environ.get("MIGRATION_PREFLIGHT_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted database URL.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        report = (
            read_only_preflight_0055(engine)
            if args.revision == "0055"
            else read_only_preflight_0130(engine)
        )
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
