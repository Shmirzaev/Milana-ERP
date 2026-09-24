"""Read-only preflight for migration 0130's account permission change.

Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted connection URL and run:
    python scripts/migration_preflight.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.migrations.preflight import read_only_preflight_0130  # noqa: E402


def main() -> int:
    database_url = os.environ.get("MIGRATION_PREFLIGHT_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted database URL.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        report = read_only_preflight_0130(engine)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
