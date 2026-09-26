"""Read-only preflight for data-affecting migrations.

Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted connection URL and run:
    python scripts/migration_preflight.py --revision 0130
    python scripts/migration_preflight.py --revision 0055
    python scripts/migration_preflight.py --revision 0091
    python scripts/migration_preflight.py --revision 0092
    python scripts/migration_preflight.py --revision 0101
    python scripts/migration_preflight.py --revision 0107
    python scripts/migration_preflight.py --revision 0090
    python scripts/migration_preflight.py --revision both
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

from app.migrations.preflight import (  # noqa: E402
    read_only_preflight_0055,
    read_only_preflight_0091_0092,
    read_only_preflight_0130,
)
from app.migrations.preflight_0126 import read_only_preflight_0126  # noqa: E402
from app.migrations.preflight_0101 import read_only_preflight_0101  # noqa: E402
from app.migrations.preflight_0107 import read_only_preflight_0107  # noqa: E402
from app.migrations.preflight_0090 import read_only_preflight_0090  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only migration impact preview")
    parser.add_argument("--revision", choices=("0055", "0090", "0091", "0092", "0101", "0107", "0126", "0130", "both"), default="0130")
    args = parser.parse_args()
    database_url = os.environ.get("MIGRATION_PREFLIGHT_DATABASE_URL")
    if not database_url:
        raise SystemExit("Set MIGRATION_PREFLIGHT_DATABASE_URL to a restricted database URL.")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if args.revision == "0055":
            report = read_only_preflight_0055(engine)
        elif args.revision == "0090":
            report = read_only_preflight_0090(engine)
        elif args.revision in {"0091", "0092", "both"}:
            report = read_only_preflight_0091_0092(
                engine,
                revision=None if args.revision == "both" else args.revision,
            )
        elif args.revision == "0101":
            report = read_only_preflight_0101(engine)
        elif args.revision == "0107":
            report = read_only_preflight_0107(engine)
        elif args.revision == "0126":
            report = read_only_preflight_0126(engine)
        else:
            report = read_only_preflight_0130(engine)
    finally:
        engine.dispose()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
