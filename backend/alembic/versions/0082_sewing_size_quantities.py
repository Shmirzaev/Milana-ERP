"""persist partial sewing output by size

Revision ID: 0082_sewing_size_quantities
Revises: 0081_purchasing_approval_details
"""

import sqlalchemy as sa
from alembic import op


revision = "0082_sewing_size_quantities"
down_revision = "0081_purchasing_approval_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sewing_records",
        sa.Column("size_quantities", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sewing_records", "size_quantities")
