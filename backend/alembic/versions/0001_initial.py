"""initial schema (frozen historical bootstrap)

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01

"""
from alembic import op
from pathlib import Path
from runpy import run_path

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _metadata():
    # The installed alembic package owns that import name; load our adjacent
    # snapshot by path instead of importing mutable application model metadata.
    snapshot = Path(__file__).resolve().parents[1] / "bootstrap_schema.py"
    return run_path(str(snapshot))["build_metadata"]()


def upgrade():
    bind = op.get_bind()
    _metadata().create_all(bind=bind)


def downgrade():
    bind = op.get_bind()
    _metadata().drop_all(bind=bind)
