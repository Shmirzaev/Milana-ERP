"""add kroy number to daily sewing reports

Revision ID: 0066_daily_sewing_kroy_no
Revises: 0065_manual_sewing_no_order
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0066_daily_sewing_kroy_no"
down_revision = "0065_manual_sewing_no_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sewing_daily_reports", sa.Column("kroy_no", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("sewing_daily_reports", "kroy_no")
