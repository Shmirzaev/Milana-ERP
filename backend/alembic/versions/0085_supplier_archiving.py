"""add safe supplier archiving

Revision ID: 0085_supplier_archiving
Revises: 0084_model_group_key
"""

from alembic import op
import sqlalchemy as sa


revision = "0085_supplier_archiving"
down_revision = "0084_model_group_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "suppliers",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("suppliers", "is_active")
