"""add the layup operator name to cutting records

Revision ID: 0074_cutting_nastilchi
Revises: 0073_archive_depleted_batches
"""

import sqlalchemy as sa
from alembic import op


revision = "0074_cutting_nastilchi"
down_revision = "0073_archive_depleted_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cutting_records",
        sa.Column("layup_operator_name", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cutting_records", "layup_operator_name")
