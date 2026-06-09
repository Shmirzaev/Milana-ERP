"""Hard reset helpers for test/demo environments.

This module wipes application tables, clears generated barcode assets,
and re-runs the seed to restore baseline records.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db.base import Base
from app.db.seed import seed
from app.db.session import engine

log = logging.getLogger(__name__)


def _truncate_all_tables() -> int:
    table_names = [t.name for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
    if not table_names:
        return 0

    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            quoted = ", ".join(f'"{name}"' for name in table_names)
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))  # nosec B608 - metadata table names only.
        else:
            # SQLite/tests fallback: delete rows table-by-table.
            for name in reversed(table_names):
                conn.execute(text(f'DELETE FROM "{name}"'))  # nosec B608 - metadata table names only.
            if conn.dialect.name == "sqlite":
                try:
                    conn.execute(text("DELETE FROM sqlite_sequence"))
                except Exception as exc:
                    log.debug("Could not reset sqlite_sequence during demo reset: %s", exc)
    return len(table_names)


def _clear_barcode_storage() -> int:
    root = Path(settings.BARCODE_STORAGE_DIR)
    if not root.exists():
        return 0

    removed = 0
    for child in root.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
            removed += 1
    return removed


def reset_to_seed() -> dict[str, int]:
    """Reset database and barcode files back to a clean seeded baseline."""
    table_count = _truncate_all_tables()
    barcode_file_count = _clear_barcode_storage()
    seed()
    return {
        "tables_truncated": table_count,
        "barcode_files_deleted": barcode_file_count,
    }


if __name__ == "__main__":
    result = reset_to_seed()
    print(
        "Reset complete. "
        f"tables_truncated={result['tables_truncated']}, "
        f"barcode_files_deleted={result['barcode_files_deleted']}"
    )
