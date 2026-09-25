"""Alembic revision IDs must fit the default version table column."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[2]


def test_revision_ids_fit_alembic_version_column():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    revisions = list(script.walk_revisions())

    assert revisions
    oversized = [(revision.revision, len(revision.revision)) for revision in revisions if len(revision.revision) > 32]
    assert oversized == [], f"Alembic version_num is VARCHAR(32): {oversized}"
